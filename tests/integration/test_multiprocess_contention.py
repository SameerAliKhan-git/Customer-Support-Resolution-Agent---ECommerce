"""Tests for multi-worker contention, concurrent claims, and simultaneous execution safety."""
import asyncio
import pytest
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import PaymentRecord, RefundProposal, Approval, RefundOperation
from app.db.operations import WorkItem
from app.services.jobs import claim, enqueue
from app.services.refund_service import refund_service
from app.services.approval_service import approval_service
from app.workflows.engine import workflow_engine

@pytest.mark.asyncio
async def test_multi_worker_claim_contention():
    """Verify that when multiple workers contend for the same work item, exactly one claims it."""
    async with AsyncSessionLocal() as db:
        run_id = "run_contention_test_1"
        job_id = await enqueue(db, run_id, "start", {"run_id": run_id})
        await db.commit()

    # Simulate 5 concurrent workers attempting to claim the job simultaneously
    async def worker_attempt(worker_id):
        return await claim(f"worker_{worker_id}")

    results = await asyncio.gather(*[worker_attempt(i) for i in range(5)])
    claimed_results = [r for r in results if r is not None]

    # Exactly ONE worker must have successfully claimed the job!
    assert len(claimed_results) == 1
    job_id_claimed, kind, payload, attempt = claimed_results[0]
    assert job_id_claimed == job_id
    assert attempt == 1

@pytest.mark.asyncio
async def test_simultaneous_refund_execution_safety():
    """Verify that simultaneous refund execution attempts on the same proposal execute exactly once."""
    state = await workflow_engine.start_workflow("cust_1001", "Please refund my headphones", "ord_1001")
    proposal_id = state["proposed_action_id"]

    async with AsyncSessionLocal() as db:
        approval = (await db.execute(select(Approval).where(Approval.proposal_id == proposal_id))).scalar_one()
        await approval_service.decide_approval(db, approval.id, "APPROVED", "rev_test", "Reviewer")

    # Launch two concurrent refund executions
    async def run_exec(worker_tag):
        async with AsyncSessionLocal() as db:
            return await refund_service.execute_approved_refund(
                db=db,
                proposal_id=proposal_id,
                reviewer_id=worker_tag,
                idempotency_key=f"simult_key_{proposal_id}"
            )

    res1, res2 = await asyncio.gather(run_exec("worker_A"), run_exec("worker_B"))

    # Both results report the verified outcome, but only ONE refund operation exists
    assert res1["success"] is True or res2["success"] is True

    async with AsyncSessionLocal() as db:
        # Check refund operations count for this proposal
        ops = (await db.execute(select(RefundOperation).where(RefundOperation.proposal_id == proposal_id))).scalars().all()
        assert len(ops) == 1
        assert ops[0].status == "SUCCEEDED"

        # Check payment record: ledger balance was decremented exactly once!
        payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == "ord_1001"))).scalar_one()
        assert payment.refunded_amount_minor == 24999
        assert payment.reserved_refund_minor == 0

@pytest.mark.asyncio
async def test_concurrent_balance_reservation_race():
    """Verify that racing proposals cannot overcommit payment balance."""
    # ord_1001 total amount is 24999. Try to create two proposals of 20000 each concurrently.
    async def create_racing_prop(tag):
        try:
            async with AsyncSessionLocal() as db:
                return await approval_service.create_proposal(
                    db=db,
                    ticket_id="tkt_1001",
                    order_id="ord_1001",
                    customer_id="cust_1001",
                    amount_minor=20000,
                    reason=f"Claim {tag}",
                    evidence_refs=[],
                    policy_refs=["refund_policy_v1:section_3"]
                )
        except ValueError as e:
            return str(e)

    r1, r2 = await asyncio.gather(create_racing_prop("prop_1"), create_racing_prop("prop_2"))

    # Exactly one proposal can succeed or both must respect balance; total reserved <= total amount
    async with AsyncSessionLocal() as db:
        payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == "ord_1001"))).scalar_one()
        assert payment.refunded_amount_minor + payment.reserved_refund_minor <= payment.amount_minor
