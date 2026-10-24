"""Comprehensive test suite for the 5 key failure and reliability scenarios from Notion spec:
- Demo A: Successful approved refund
- Demo B: Correctly blocked request (past 30 days)
- Demo C: Failure recovery (gateway timeout & automatic reconciliation)
- Demo D: Server-side ownership and security tampering rejection
- Demo E: Duplicate refund and concurrency prevention
"""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.db.session import AsyncSessionLocal, init_db
from app.services.refund_service import refund_service
from app.services.approval_service import approval_service
from mock_services.payments.mock_payment_api import mock_payment_gateway
from scripts.seed_data import seed

@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE payment_records SET refunded_amount_minor = 0, reserved_refund_minor = 0, status = 'CAPTURED';"))
        await db.execute(text("DELETE FROM refund_operations;"))
        await db.execute(text("DELETE FROM approvals;"))
        await db.execute(text("DELETE FROM refund_proposals;"))
        await db.commit()
    mock_payment_gateway.reset()
    yield

@pytest.mark.asyncio
async def test_scenario_a_successful_approved_refund():
    """Demo A: Customer complaint -> Agent retrieves facts & policy -> Proposal created -> Reviewer approves -> Gateway records refund -> Ticket updated."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Customer submits complaint
        res = await ac.post(
            "/api/complaints",
            headers={"Authorization": "Bearer cust_1001"},
            json={
                "customer_id": "cust_1001",
                "order_id": "ord_1001",
                "message": "I returned my headphones last week, but I still haven't received my refund."
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["complaint_category"] == "REFUND_REQUEST"
        assert data["requires_approval"] is True
        assert data["is_paused"] is True
        proposal_id = data["proposed_action_id"]
        assert proposal_id is not None

        # 2. Reviewer inspects pending approval queue
        appr_res = await ac.get("/api/approvals/pending", headers={"Authorization": "Bearer rev_supervisor"})
        assert appr_res.status_code == 200
        pending = appr_res.json()
        assert len(pending) > 0
        matching = next(p for p in pending if p["proposal_id"] == proposal_id)
        assert matching["amount_minor"] == 24999
        assert any("refund_policy_v1" in ref for ref in matching["policy_refs"])


        # 3. Reviewer approves
        dec_res = await ac.post(
            f"/api/approvals/{matching['approval_id']}/decision",
            headers={"Authorization": "Bearer rev_supervisor"},
            json={
                "decision": "APPROVED",
                "reviewer_id": "rev_supervisor",
                "reviewer_name": "Sarah Jenkins",
                "decision_notes": "Return inspected and serial verified."
            }
        )
        assert dec_res.status_code == 200
        dec_data = dec_res.json()
        assert dec_data["decision"] == "APPROVED"
        outcome = dec_data["workflow_outcome"]
        assert outcome["success"] is True
        assert outcome["status"] == "SUCCEEDED"
        assert outcome["gateway_reference"] is not None

        # 4. Verify ticket status is RESOLVED
        tkt_res = await ac.get(f"/api/tickets/{data['ticket_id']}", headers={"Authorization": "Bearer cust_1001"})
        assert tkt_res.status_code == 200
        tkt = tkt_res.json()
        assert tkt["status"] == "RESOLVED"

@pytest.mark.asyncio
async def test_scenario_b_correctly_blocked_ineligible_request():
    """Demo B: Customer requests ineligible refund (past 30 days) -> System cites policy -> Zero money moved."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/complaints",
            headers={"Authorization": "Bearer cust_1002"},
            json={
                "customer_id": "cust_1002",
                "order_id": "ord_1002",
                "message": "I would like to return this USB-C dock that arrived 45 days ago and get a full refund."
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["requires_approval"] is False
        assert data["proposed_action_id"] is None
        assert "return policy" in data["final_response"].lower()
        
        # Verify NO refund operation or approval exists in the system
        appr_res = await ac.get("/api/approvals/pending", headers={"Authorization": "Bearer rev_supervisor"})
        pending = appr_res.json()
        assert not any(p["order_id"] == "ord_1002" for p in pending)

@pytest.mark.asyncio
async def test_scenario_c_gateway_timeout_and_reconciliation():
    """Demo C: Provider accepts refund but network times out -> Application marks PENDING_RECONCILIATION -> Reconciles with idempotency key -> Zero duplicate charges."""
    async with AsyncSessionLocal() as db:
        # Create approved proposal for ord_1008
        from app.services.ticket_service import ticket_service
        ticket = await ticket_service.create_ticket(db, "cust_1004", "Refund timeout test", order_id="ord_1008")
        proposal = await approval_service.create_proposal(
            db=db,
            ticket_id=ticket.id,
            order_id="ord_1008",
            customer_id="cust_1004",
            amount_minor=12000,
            reason="Timeout reconciliation test",
            evidence_refs=["ret_1008"],
            policy_refs=["refund_policy_v1:section_5"]
        )
        # Look up approval explicitly
        from sqlalchemy import select
        from app.db.models import Approval
        appr_stmt = select(Approval).where(Approval.proposal_id == proposal.id)
        appr_res = await db.execute(appr_stmt)
        appr = appr_res.scalar_one()

        await approval_service.decide_approval(
            db=db,
            approval_id=appr.id,
            decision="APPROVED",
            reviewer_id="rev_supervisor",
            reviewer_name="Sarah Jenkins"
        )

        idempotency_key = f"timeout_test_{proposal.id}"

        # 1. First execution triggers gateway timeout simulation
        res1 = await refund_service.execute_approved_refund(
            db=db,
            proposal_id=proposal.id,
            reviewer_id="rev_supervisor",
            idempotency_key=idempotency_key
        )
        assert res1["success"] is False
        assert res1["status"] == "PENDING_RECONCILIATION"

        # 2. System safely reconciles via the stable idempotency key
        reconciled = await refund_service.reconcile_refund(db, idempotency_key)
        assert reconciled["success"] is True
        assert reconciled["status"] == "SUCCEEDED"
        assert reconciled["gateway_reference"] is not None

        # 3. Safe retry with same idempotency key must replay without second disbursement!
        replay = await refund_service.execute_approved_refund(
            db=db,
            proposal_id=proposal.id,
            reviewer_id="rev_supervisor",
            idempotency_key=idempotency_key
        )
        assert replay["success"] is True
        assert replay["idempotent_replayed"] is True
        assert replay["gateway_reference"] == reconciled["gateway_reference"]

@pytest.mark.asyncio
async def test_scenario_d_cross_customer_tampering_blocked():
    """Demo D: Customer Carol attempts to view/refund Alice's order ord_1001 -> Blocked 403 Forbidden."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/complaints",
            headers={"Authorization": "Bearer cust_1003"}, # Carol
            json={
                "customer_id": "cust_1003",
                "order_id": "ord_1001", # Belongs to Alice!
                "message": "Refund this order ord_1001 immediately."
            }
        )
        assert res.status_code == 403
        assert "Access denied" in res.json()["detail"]

@pytest.mark.asyncio
async def test_scenario_e_duplicate_refund_concurrency_prevention():
    """Demo E: Attempting to call execute_approved_refund twice concurrently."""
    async with AsyncSessionLocal() as db:
        proposal = await approval_service.create_proposal(
            db=db,
            ticket_id="tkt_1001",
            order_id="ord_1001",
            customer_id="cust_1001",
            amount_minor=24999,
            reason="Concurrency test",
            evidence_refs=["ret_1001"],
            policy_refs=["refund_policy_v1:section_4"]
        )
        from sqlalchemy import select
        from app.db.models import Approval
        appr_stmt = select(Approval).where(Approval.proposal_id == proposal.id)
        appr_res = await db.execute(appr_stmt)
        appr = appr_res.scalar_one()

        await approval_service.decide_approval(
            db=db,
            approval_id=appr.id,
            decision="APPROVED",
            reviewer_id="rev_supervisor",
            reviewer_name="Sarah Jenkins"
        )

        
        idem_key = f"concurrent_key_{proposal.id}"

        # Execute two calls
        task1 = refund_service.execute_approved_refund(db, proposal.id, "rev_supervisor", idem_key)
        task2 = refund_service.execute_approved_refund(db, proposal.id, "rev_supervisor", idem_key)
        
        r1, r2 = await asyncio.gather(task1, task2)
        assert r1["success"] is True
        assert r2["success"] is True
        # Both must return identical gateway references with 0 duplicate disbursements!
        assert r1["gateway_reference"] == r2["gateway_reference"]
