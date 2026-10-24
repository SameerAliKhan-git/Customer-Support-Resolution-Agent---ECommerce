"""Unit tests for typed read and write tools."""
import pytest
from app.db.session import AsyncSessionLocal, init_db
from app.tools.read_tools import read_tools
from app.tools.write_tools import write_tools
from scripts.seed_data import seed

@pytest.mark.asyncio
async def test_read_tools_ownership_enforcement():
    await init_db()
    async with AsyncSessionLocal() as db:
        # Alice querying her own order ord_1001
        res = await read_tools.get_order("ord_1001", "cust_1001", db)
        assert res["success"] is True
        assert res["order_id"] == "ord_1001"

        # Bob attempting to query Alice's order ord_1001 -> MUST be blocked!
        unauthorized = await read_tools.get_order("ord_1001", "cust_1002", db)
        assert unauthorized["success"] is False
        assert unauthorized["error_code"] == "UNAUTHORIZED_ORDER_ACCESS"

@pytest.mark.asyncio
async def test_return_and_payment_status_tools():
    async with AsyncSessionLocal() as db:
        ret = await read_tools.get_return_status("ord_1001", "cust_1001", db)
        assert ret["success"] is True
        assert ret["status"] == "INSPECTION_PASSED"

        pay = await read_tools.get_payment_status("ord_1001", "cust_1001", db)
        assert pay["success"] is True
        assert pay["amount_minor"] == 24999
        assert pay["currency"] == "USD"

@pytest.mark.asyncio
async def test_proposal_creation_does_not_move_funds():
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text
        await db.execute(text("UPDATE payment_records SET refunded_amount_minor = 0, reserved_refund_minor = 0, status = 'CAPTURED';"))
        await db.execute(text("DELETE FROM refund_proposals;"))
        await db.commit()

        prop_res = await write_tools.create_refund_proposal(
            ticket_id="tkt_1001",
            order_id="ord_1001",
            authenticated_customer_id="cust_1001",
            amount_minor=24999,
            reason="Test proposal",
            evidence_refs=["ret_1001"],
            policy_refs=["refund_policy_v1:section_3"],
            db=db
        )

        assert prop_res["success"] is True
        assert prop_res["requires_approval"] is True
        assert prop_res["status"] == "PENDING"
