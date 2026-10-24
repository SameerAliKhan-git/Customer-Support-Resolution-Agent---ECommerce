"""Regression tests for audit findings, queue durability and provider contracts."""
import datetime
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from httpx import ASGITransport,AsyncClient
from app.main import app
from app.db.models import PaymentRecord,ReturnRecord,Order,RefundOperation,Approval,RefundProposal
from app.db.session import AsyncSessionLocal
from app.services.approval_service import approval_service
from app.services.refund_service import refund_service
from app.workflows.engine import workflow_engine

async def approved():
    state=await workflow_engine.start_workflow('cust_1001','Please refund my returned headphones','ord_1001')
    async with AsyncSessionLocal() as db:
        approval=(await db.execute(select(Approval).where(Approval.proposal_id==state['proposed_action_id']))).scalar_one()
        await approval_service.decide_approval(db,approval.id,'APPROVED','rev_test','Reviewer')
    return state

@pytest.mark.parametrize('defect',['late_return','voided_payment','wrong_ticket','future_return'])
async def test_service_gate_rejects_ineligible(defect):
    async with AsyncSessionLocal() as db:
        ticket='tkt_1001'
        if defect=='voided_payment':
            pay=(await db.execute(select(PaymentRecord).where(PaymentRecord.order_id=='ord_1001'))).scalar_one()
            pay.status='VOIDED'
        elif defect=='wrong_ticket':
            ticket='tkt_1002'
        else:
            order=await db.get(Order,'ord_1001')
            returned=(await db.execute(select(ReturnRecord).where(ReturnRecord.order_id=='ord_1001'))).scalar_one()
            returned.created_at=order.delivery_date+datetime.timedelta(days=45 if defect=='late_return' else -1)
        await db.commit()
        with pytest.raises(ValueError):
            await approval_service.create_proposal(db,ticket,'ord_1001','cust_1001',24999,'test',[],['refund_policy_v1:section_5'])

async def test_crash_before_send_reuses_original_key():
    state=await approved()
    async with AsyncSessionLocal() as db:
        proposal=await db.get(RefundProposal,state['proposed_action_id'])
        db.add(RefundOperation(id='op_crash',proposal_id=proposal.id,order_id=proposal.order_id,
            customer_id=proposal.customer_id,amount_minor=proposal.amount_minor,currency=proposal.currency,
            idempotency_key='crash-original-key',status='PROCESSING',attempt_count=1,request_payload={'reason':proposal.reason}))
        await db.commit()
        result=await refund_service.execute_approved_refund(db,proposal.id,'rev_test','different-key')
        assert result['success']
        payment=(await db.execute(select(PaymentRecord).where(PaymentRecord.order_id==proposal.order_id))).scalar_one()
        assert payment.refunded_amount_minor==24999 and payment.reserved_refund_minor==0
        assert (await db.execute(select(RefundOperation))).scalars().one().idempotency_key=='crash-original-key'

async def test_decline_allows_fresh_proposal_requires_fresh_approval():
    state=await approved()
    async with AsyncSessionLocal() as db:
        old=await db.get(RefundProposal,state['proposed_action_id'])
        result=await refund_service.execute_approved_refund(db,old.id,'rev_test','fail_test_decline')
        assert result['status'] in ('DECLINED', 'FAILED')
        new=await approval_service.create_proposal(db,old.ticket_id,old.order_id,old.customer_id,old.amount_minor,
            old.reason,old.evidence_refs,old.policy_refs)
        assert new.id!=old.id and new.status=='PENDING'
        assert not (await refund_service.execute_approved_refund(db,new.id,'rev_test'))['success']

async def test_database_rejects_overcommitted_balance():
    async with AsyncSessionLocal() as db:
        pay=(await db.execute(select(PaymentRecord).where(PaymentRecord.order_id=='ord_1001'))).scalar_one()
        pay.reserved_refund_minor=pay.amount_minor+1
        with pytest.raises(IntegrityError):
            await db.commit()

async def test_durable_submission_idempotency_and_restarted_worker(monkeypatch):
    from app.config import settings
    from app.services.jobs import work_once,recover_pending
    monkeypatch.setattr(settings,'ASYNC_WORKFLOWS',True)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        headers={'Authorization':'Bearer cust_1001','Idempotency-Key':'customer-click-1'}
        body={'order_id':'ord_1001','message':'Please refund my returned headphones'}
        first=await client.post('/api/complaints',headers=headers,json=body)
        second=await client.post('/api/complaints',headers=headers,json=body)
        assert first.status_code==second.status_code==202
        assert first.json()['run_id']==second.json()['run_id']
        conflict=await client.post('/api/complaints',headers=headers,json={**body,'message':'a different message'})
        assert conflict.status_code==409
        assert await work_once('worker-1')
        run_id=first.json()['run_id']
        state=await workflow_engine.get_workflow_state(run_id)
        assert state['is_paused']
        async with AsyncSessionLocal() as db:
            approval=(await db.execute(select(Approval).where(Approval.proposal_id==state['proposed_action_id']))).scalar_one()
            # Simulate API death immediately after the committed reviewer decision.
            await approval_service.decide_approval(db,approval.id,'APPROVED','rev_test','Reviewer')
        await recover_pending()
        assert await work_once('worker-2')
        state=await workflow_engine.get_workflow_state(run_id)
        assert state['execution_status']=='SUCCEEDED'

async def test_stripe_processing_is_not_success_claim():
    from app.integrations.payments import StripeGateway
    result=StripeGateway.normalize({'id':'re_test','status':'pending','amount':100,'currency':'usd'})
    assert result['status']=='PROCESSING'

async def test_oidc_customer_subject_is_mapped_server_side(monkeypatch):
    from app.config import settings
    from app.auth import oidc
    from app.db.models import Customer
    monkeypatch.setattr(settings,'AUTH_MODE','oidc')
    async def verifier(token):return {'sub':'external-subject'},'customer'
    monkeypatch.setattr(oidc,'verify_token',verifier)
    async with AsyncSessionLocal() as db:
        customer=await db.get(Customer,'cust_1001');customer.external_auth_subject='external-subject';await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/api/tickets',headers={'Authorization':'Bearer some-token'})
        assert response.status_code==200
        assert all(t['customer_id']=='cust_1001' for t in response.json())
