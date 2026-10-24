"""Stripe webhook inbox: signatures authenticate delivery; reconciliation verifies business state."""
import hashlib
import hmac
import json
import time
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import RefundOperation
from app.db.operations import ProviderEvent
from app.db.workflow_store import find_run
from app.services.jobs import enqueue

router=APIRouter()

@router.post('/integrations/stripe/webhook')
async def stripe_webhook(request: Request):
    if settings.PAYMENT_PROVIDER != 'stripe' or not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503,'Webhook is not configured.')
    body=await request.body()
    if len(body)>262144:
        raise HTTPException(413,'Event is too large.')
    try:
        parts=[p.split('=',1) for p in request.headers.get('stripe-signature','').split(',')]
        timestamp=next(int(v) for k,v in parts if k=='t')
        expected=hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode(),str(timestamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
        if abs(time.time()-timestamp)>300 or not any(k=='v1' and hmac.compare_digest(expected,v) for k,v in parts):
            raise ValueError()
        event=json.loads(body)
        if not isinstance(event.get('id'),str) or not event['id'].startswith('evt_'):
            raise ValueError()
    except (ValueError,TypeError,StopIteration):
        raise HTTPException(400,'Invalid event signature or payload.')
    async with AsyncSessionLocal() as db:
        if await db.get(ProviderEvent,event['id']):
            return {'received':True,'duplicate':True}
        obj=event.get('data',{}).get('object',{})
        # Store only routing data; payment/card/customer payloads are deliberately excluded.
        db.add(ProviderEvent(id=event['id'],payload={'type':event.get('type'),'reference':obj.get('id')},received_at=datetime.utcnow()))
        reference=obj.get('id')
        op=(await db.execute(select(RefundOperation).where(RefundOperation.gateway_reference==reference))).scalar_one_or_none()
        if op:
            from app.db.models import RefundProposal
            proposal=await db.get(RefundProposal,op.proposal_id)
            run_id=await find_run(proposal.ticket_id)
            if run_id:
                await enqueue(db,run_id,revive=True)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        return {'received':True}
