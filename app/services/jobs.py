"""Durable job queue. Claim transactions finish before workflow/network execution."""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, update, or_, and_, delete
from sqlalchemy.exc import IntegrityError
from app.db.session import AsyncSessionLocal
from app.db.models import Ticket, Approval, RefundProposal, RefundOperation
from app.db.operations import WorkItem, RequestReceipt, ExecutionLease, RateBucket
from app.db.workflow_store import WorkflowRun

log = logging.getLogger(__name__)

def job_id(run_id, kind):
    return f'{kind}:{run_id}'

async def enqueue(db, run_id, kind='resume', payload=None, revive=False):
    ident = job_id(run_id, kind)
    job = await db.get(WorkItem, ident)
    if not job:
        db.add(WorkItem(id=ident, kind=kind, payload=payload or {'run_id': run_id},
            status='READY', attempts=0, available_at=datetime.utcnow()))
    elif revive and job.status == 'DONE' and job.available_at <= datetime.utcnow():
        job.status, job.available_at = 'READY', datetime.utcnow()
    return ident

async def submit(customer_id, message, order_id=None, key=None):
    """Ticket, initial run, receipt and initial job commit atomically."""
    fingerprint = hashlib.sha256(json.dumps([customer_id,message,order_id]).encode()).hexdigest()
    receipt_id = hashlib.sha256(f'{customer_id}:{key or uuid.uuid4().hex}'.encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        receipt = await db.get(RequestReceipt, receipt_id)
        if receipt:
            if receipt.fingerprint != fingerprint:
                raise ValueError('Idempotency key was already used with another request.')
            run = await db.get(WorkflowRun, receipt.run_id)
            return dict(run.state)
        run_id, ticket_id = 'run_'+uuid.uuid4().hex[:12], 'tkt_'+uuid.uuid4().hex[:12]
        state = dict(run_id=run_id,ticket_id=ticket_id,authenticated_customer_id=customer_id,
            customer_message=message,order_id=order_id,execution_status='QUEUED',is_completed=False,is_paused=False)
        db.add(Ticket(id=ticket_id, customer_id=customer_id, order_id=order_id,
            title=' '.join(message.split()[:8]), customer_message=message, notes=[]))
        await db.flush()
        db.add(WorkflowRun(id=run_id,ticket_id=ticket_id,state=state))
        db.add(RequestReceipt(id=receipt_id,fingerprint=fingerprint,run_id=run_id))
        await enqueue(db,run_id,'start',dict(customer_id=customer_id,message=message,order_id=order_id,ticket_id=ticket_id,run_id=run_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            receipt = await db.get(RequestReceipt, receipt_id)
            if not receipt or receipt.fingerprint != fingerprint:
                raise ValueError('Duplicate or conflicting request.')
            return dict((await db.get(WorkflowRun, receipt.run_id)).state)
        return state

async def claim(owner):
    now = datetime.utcnow()
    eligible = or_(and_(WorkItem.status=='READY',WorkItem.available_at<=now),
        and_(WorkItem.status=='RUNNING',WorkItem.lease_until<now))
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(WorkItem).where(eligible).order_by(WorkItem.available_at)
            .with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not job:
            return None
        attempt = job.attempts + 1
        changed = await db.execute(update(WorkItem).where(WorkItem.id==job.id,eligible).values(
            status='RUNNING',owner=owner,lease_until=now+timedelta(seconds=120),attempts=WorkItem.attempts+1))
        await db.commit()
        return (job.id,job.kind,dict(job.payload),attempt) if changed.rowcount else None

async def recover_pending():
    """Recover committed reviewer decisions and uncertain operations after any crash."""
    from app.services.approval_service import approval_service
    async with AsyncSessionLocal() as db:
        await approval_service.list_pending_approvals(db)  # expires pending reviews and releases reservations
        runs = (await db.execute(select(WorkflowRun))).scalars().all()
        for run in runs:
            if run.state.get('is_completed'):
                continue
            proposal_id = run.state.get('proposed_action_id')
            if proposal_id:
                approval = (await db.execute(select(Approval).where(Approval.proposal_id==proposal_id))).scalar_one_or_none()
                if approval and approval.decision in ('APPROVED','REJECTED','EXPIRED'):
                    await enqueue(db, run.id, revive=True)
        await db.commit()

async def work_once(owner=None):
    from app.workflows.engine import workflow_engine
    owner = owner or uuid.uuid4().hex
    claimed = await claim(owner)
    if not claimed:
        return False
    ident,kind,payload,attempts = claimed
    error = None
    try:
        if kind == 'start':
            await asyncio.wait_for(workflow_engine.start_workflow(**payload),90)
        elif kind == 'resume':
            await asyncio.wait_for(workflow_engine.resume_workflow(payload['run_id'],{}),90)
        elif kind == 'ticket_sync':
            from app.integrations.ecommerce import sync_ticket
            await sync_ticket(payload,ident)
        else:
            raise ValueError('Unknown job kind')
    except Exception as exc:
        # Do not persist exception text, which can include provider tokens/customer data.
        error = type(exc).__name__
        log.warning('job_failed job=%s error=%s',ident,error)
    async with AsyncSessionLocal() as db:
        job = await db.get(WorkItem,ident)
        if job.owner == owner:
            job.status = ('DEAD' if attempts >= 8 else 'READY') if error else 'DONE'
            job.error_code = error
            job.available_at = datetime.utcnow()+timedelta(seconds=min(300,2**attempts) if error else 30)
            job.lease_until = None
            await db.commit()
    return True

async def main():
    owner=uuid.uuid4().hex
    while True:
        async with AsyncSessionLocal() as db:
            await db.merge(ExecutionLease(id='worker-heartbeat',owner=owner,expires_at=datetime.utcnow()+timedelta(seconds=120)))
            await db.execute(delete(RateBucket).where(RateBucket.expires_at<datetime.utcnow()))
            await db.commit()
        await recover_pending()
        if not await work_once(owner):
            await asyncio.sleep(2)

if __name__ == '__main__':
    asyncio.run(main())
