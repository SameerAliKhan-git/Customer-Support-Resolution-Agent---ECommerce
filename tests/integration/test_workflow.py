"""Integration tests for the LangGraph resolution workflow and FastAPI endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import init_db
from scripts.seed_data import seed

@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Customer Support Resolution Agent"
        dashboard = await ac.get("/")
        assert dashboard.status_code == 200
        assert 'id="complaint-form"' in dashboard.text

@pytest.mark.asyncio
async def test_demo_scenarios_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/demo/scenarios")
        assert res.status_code == 200
        scenarios = res.json()
        assert len(scenarios) >= 3

@pytest.mark.asyncio
async def test_submit_complaint_and_list_tickets():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Submit complaint
        res = await ac.post(
            "/api/complaints",
            headers={"Authorization": "Bearer cust_1003"},
            json={
                "customer_id": "cust_1003",
                "order_id": "ord_1003",
                "message": "Can you check where my mechanical keyboard is right now?"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["complaint_category"] == "ORDER_STATUS"
        assert "shipped" in data["final_response"].lower() or "transit" in data["final_response"].lower()

        # Query tickets
        tkt_res = await ac.get("/api/tickets", headers={"Authorization": "Bearer cust_1003"})
        assert tkt_res.status_code == 200
        tickets = tkt_res.json()
        assert len(tickets) > 0
