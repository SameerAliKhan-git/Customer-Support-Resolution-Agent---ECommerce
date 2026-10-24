"""Tests for production topology, startup guards, /api/ready, and async worker execution."""
from datetime import datetime, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app, lifespan
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.operations import WorkItem, ExecutionLease
from app.db.workflow_store import WorkflowRun
from app.services.jobs import work_once

@pytest.mark.asyncio
async def test_production_startup_guards(monkeypatch):
    """Verify that production mode strictly enforces security and deployment guards."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    # Guard 1: Demo auth must be rejected in production
    monkeypatch.setattr(settings, "AUTH_MODE", "demo")
    with pytest.raises(RuntimeError, match="Production requires configured OIDC authentication"):
        async with lifespan(app):
            pass

    # Guard 2: Auto schema creation and demo seeding must be rejected in production
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://auth.example.com")
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", True)
    with pytest.raises(RuntimeError, match="Production requires migrations"):
        async with lifespan(app):
            pass

    # Guard 3: Non-PostgreSQL database must be rejected in production
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(settings, "SEED_DEMO_DATA", False)
    monkeypatch.setattr(settings, "ASYNC_WORKFLOWS", True)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///support.db")
    with pytest.raises(RuntimeError, match="Production requires PostgreSQL"):
        async with lifespan(app):
            pass

    # Guard 4: Default dev SECRET_KEY must be rejected in production
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://support:pwd@localhost:5432/support")
    monkeypatch.setattr(settings, "SECRET_KEY", "super-secret-dev-key-change-in-prod-xyz789")
    with pytest.raises(RuntimeError, match="Production requires a strong non-default SECRET_KEY"):
        async with lifespan(app):
            pass

@pytest.mark.asyncio
async def test_api_ready_probe(monkeypatch):
    """Verify /api/ready fails when worker heartbeat is missing in async mode, and passes when active."""
    monkeypatch.setattr(settings, "ASYNC_WORKFLOWS", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Initially, without worker heartbeat in async mode, /api/ready returns 503
        resp = await client.get("/api/ready")
        assert resp.status_code == 503

        # Add valid worker heartbeat
        async with AsyncSessionLocal() as db:
            await db.merge(ExecutionLease(
                id="worker-heartbeat",
                owner="test_worker_1",
                expires_at=datetime.utcnow() + timedelta(minutes=5)
            ))
            await db.commit()

        # Now /api/ready returns 200
        resp2 = await client.get("/api/ready")
        assert resp2.status_code == 200
        assert resp2.json() == {"status": "ready"}

        # If heartbeat expires, /api/ready returns 503 again
        async with AsyncSessionLocal() as db:
            await db.merge(ExecutionLease(
                id="worker-heartbeat",
                owner="test_worker_1",
                expires_at=datetime.utcnow() - timedelta(seconds=10)
            ))
            await db.commit()

        resp3 = await client.get("/api/ready")
        assert resp3.status_code == 503

@pytest.mark.asyncio
async def test_async_workflow_submission_and_worker_claim(monkeypatch):
    """Verify async workflow submission enqueues work and worker executes it to completion."""
    monkeypatch.setattr(settings, "ASYNC_WORKFLOWS", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": "Bearer cust_1001", "Idempotency-Key": "async-test-key-1"}
        payload = {
            "customer_id": "cust_1001",
            "order_id": "ord_1001",
            "message": "Please refund my headphones ord_1001"
        }
        resp = await client.post("/api/complaints", headers=headers, json=payload)
        assert resp.status_code == 202
        state = resp.json()
        run_id = state["run_id"]
        assert resp.headers["Location"] == f"/api/workflows/{run_id}"

        # Verify job is enqueued in database as READY
        async with AsyncSessionLocal() as db:
            job = await db.get(WorkItem, f"start:{run_id}")
            assert job is not None
            assert job.status == "READY"
            assert job.kind == "start"

        # Worker picks up job and executes it
        worked = await work_once("worker_node_1")
        assert worked is True

        # Verify job status transitioned to DONE
        async with AsyncSessionLocal() as db:
            job_after = await db.get(WorkItem, f"start:{run_id}")
            assert job_after.status == "DONE"

            run = await db.get(WorkflowRun, run_id)
            assert run is not None
            # The refund request workflow has progressed (paused awaiting reviewer approval)
            assert run.state.get("is_paused") is True
            assert run.state.get("action_type") == "request_refund_approval"
