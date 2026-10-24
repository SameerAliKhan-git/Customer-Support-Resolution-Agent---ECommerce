import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.db.session import AsyncSessionLocal
from app.db.models import Approval, RefundProposal, ReturnRecord
from app.services.approval_service import approval_service
from app.services.refund_service import refund_service

@pytest.mark.asyncio
async def test_clarification_continues_same_thread():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization":"Bearer cust_1003"}
        first = (await client.post("/api/complaints",headers=headers,
            json={"customer_id":"cust_1003","message":"Where is my order?"})).json()
        response = await client.post(f"/api/workflows/{first['run_id']}/messages",headers=headers,
            json={"message":"It is ord_1003", "order_id":"ord_1003"})
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["run_id"] == first["run_id"] and state["ticket_id"] == first["ticket_id"]
        assert "shipped" in state["final_response"].lower()

@pytest.mark.asyncio
async def test_material_change_invalidates_approved_refund():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        state = (await client.post("/api/complaints",headers={"Authorization":"Bearer cust_1001"},
            json={"customer_id":"cust_1001","order_id":"ord_1001","message":"Please refund my returned item."})).json()
    async with AsyncSessionLocal() as db:
        approval = (await db.execute(select(Approval).where(Approval.proposal_id==state["proposed_action_id"]))).scalar_one()
        await approval_service.decide_approval(db,approval.id,"APPROVED","rev_supervisor","Reviewer")
        record = (await db.execute(select(ReturnRecord).where(ReturnRecord.order_id=="ord_1001"))).scalar_one()
        record.status = "INSPECTION_FAILED"
        await db.commit()
        outcome = await refund_service.execute_approved_refund(db,state["proposed_action_id"],"rev_supervisor")
        assert not outcome["success"] and "changed" in outcome["message"]

@pytest.mark.asyncio
async def test_transient_read_failures_have_bounded_retries(monkeypatch):
    from app.agents.investigator import investigation_agent
    original = investigation_agent.investigate
    calls = []
    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("synthetic read timeout")
        return await original(*args, **kwargs)
    monkeypatch.setattr(investigation_agent,"investigate",flaky)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        response = await client.post("/api/complaints",headers={"Authorization":"Bearer cust_1003"},
            json={"customer_id":"cust_1003","order_id":"ord_1003","message":"Where is my order?"})
        assert response.status_code == 200
        assert response.json()["retry_counts"] == 2 and len(calls) == 3
