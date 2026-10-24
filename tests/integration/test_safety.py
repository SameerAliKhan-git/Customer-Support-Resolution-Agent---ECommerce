"""Regression checks for authorization, durable review and truthful outcomes."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.db.session import AsyncSessionLocal
from app.db.models import Approval, PaymentRecord, RefundProposal
from app.workflows.engine import workflow_engine
from app.services.refund_service import refund_service
from app.services.approval_service import approval_service
from mock_services.payments.mock_payment_api import mock_payment_gateway

CUSTOMER = {"Authorization": "Bearer cust_1001"}
REVIEWER = {"Authorization": "Bearer rev_supervisor"}

async def complaint(client, order="ord_1001", customer="cust_1001"):
    response = await client.post("/api/complaints", headers={"Authorization": f"Bearer {customer}"},
        json={"customer_id": customer, "order_id": order, "message": "Please refund my returned item."})
    assert response.status_code == 200, response.text
    return response.json()

@pytest.mark.asyncio
async def test_access_and_durable_rejection():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/tickets")).status_code == 401
        state = await complaint(client)
        url = f"/api/workflows/{state['run_id']}"
        assert (await client.get(url, headers={"Authorization": "Bearer cust_1002"})).status_code == 403
        assert (await client.post(url + "/resume", headers=CUSTOMER,
            json={"decision": "APPROVED", "reviewer_id": "rev_fake", "reviewer_name": "Fake"})).status_code == 403
        # A new engine instance reads persisted state without a graph memory checkpoint.
        assert (await type(workflow_engine)().get_workflow_state(state["run_id"]))["is_paused"]
        queue = (await client.get("/api/approvals/pending", headers=REVIEWER)).json()
        decision_url = f"/api/approvals/{queue[0]['approval_id']}/decision"
        decision = {"decision": "REJECTED", "reviewer_id": "rev_spoofed", "reviewer_name": "Spoofed", "decision_notes": "Evidence insufficient"}
        result = await client.post(decision_url, headers=REVIEWER, json=decision)
        assert result.status_code == 200, result.text
        assert result.json()["workflow_state"]["execution_status"] == "REJECTED"
        assert (await client.get(url, headers=CUSTOMER)).json()["is_completed"]
        assert (await client.post(decision_url, headers=REVIEWER, json=decision)).status_code == 400
        async with AsyncSessionLocal() as db:
            approval = await db.get(Approval, queue[0]["approval_id"])
            assert approval.reviewer_id == "rev_supervisor"
            payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == "ord_1001"))).scalar_one()
            assert payment.reserved_refund_minor == payment.refunded_amount_minor == 0

@pytest.mark.asyncio
async def test_timeout_workflow_and_audit_trail():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        state = await complaint(client, "ord_1008", "cust_1004")
        queue = (await client.get("/api/approvals/pending", headers=REVIEWER)).json()
        result = await client.post(f"/api/approvals/{queue[0]['approval_id']}/decision", headers=REVIEWER,
            json={"decision": "APPROVED", "reviewer_id": "ignored", "reviewer_name": "ignored"})
        outcome = result.json()["workflow_outcome"]
        assert outcome["status"] == "SUCCEEDED", result.text
        assert outcome["gateway_reference"].startswith("gw_rf_")
        trail = (await client.get(f"/api/tickets/{state['ticket_id']}/audit-trail", headers=REVIEWER)).json()
        actions = {event["action"] for event in trail}
        assert {"APPROVAL_APPROVED", "REFUND_TIMEOUT_RECONCILIATION_REQUIRED", "REFUND_RECONCILED_SUCCESS"} <= actions

@pytest.mark.asyncio
async def test_concurrent_sessions_and_changed_key_cannot_double_refund():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        state = await complaint(client)
    async with AsyncSessionLocal() as db:
        approval = (await db.execute(select(Approval).where(Approval.proposal_id == state["proposed_action_id"]))).scalar_one()
        await approval_service.decide_approval(db, approval.id, "APPROVED", "rev_supervisor", "Reviewer")
    async def execute(key):
        async with AsyncSessionLocal() as db:
            return await refund_service.execute_approved_refund(db, state["proposed_action_id"], "rev_supervisor", key)
    first, second = await asyncio.gather(execute("first-key"), execute("different-key"))
    assert first["success"] and second["success"]
    assert first["gateway_reference"] == second["gateway_reference"]
    assert len(mock_payment_gateway.operations) == 1
    # Clear provider cache to simulate a provider adapter restart, then reconcile twice.
    mock_payment_gateway.reset()
    async with AsyncSessionLocal() as db:
        assert (await refund_service.reconcile_refund(db, "first-key"))["success"]
        assert (await refund_service.reconcile_refund(db, "first-key"))["success"]
        payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == "ord_1001"))).scalar_one()
        assert payment.refunded_amount_minor == 24999

@pytest.mark.asyncio
async def test_invalid_proposals_and_unapproved_resume():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        state = await complaint(client)
        result = await client.post(f"/api/workflows/{state['run_id']}/resume", headers=REVIEWER,
            json={"decision": "APPROVED", "reviewer_id": "rev_supervisor", "reviewer_name": "Reviewer"})
        assert result.status_code == 400
    async with AsyncSessionLocal() as db:
        for amount, customer in [(-1, "cust_1001"), (100, "cust_1002")]:
            with pytest.raises(ValueError):
                await approval_service.create_proposal(db, "tkt_1001", "ord_1001", customer, amount, "test", [], [])

@pytest.mark.asyncio
async def test_signed_authentication(monkeypatch):
    from app.config import settings
    from app.auth.security import issue_token
    monkeypatch.setattr(settings, "AUTH_MODE", "signed")
    monkeypatch.setattr(settings, "SECRET_KEY", "test-private-key-" * 4)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/approvals/pending", headers=REVIEWER)).status_code == 401
        token = issue_token("rev_secure", "reviewer", "Secure reviewer")
        assert (await client.get("/api/approvals/pending", headers={"Authorization": f"Bearer {token}"})).status_code == 200
        expired = issue_token("rev_secure", "reviewer", "Reviewer", expires_in=-1)
        assert (await client.get("/api/approvals/pending", headers={"Authorization": f"Bearer {expired}"})).status_code == 401
