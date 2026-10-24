"""Unit tests verifying production-grade fixes: CSP headers, OIDC discovery caching, and demo admin roles."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.auth.oidc import get_oidc_discovery, clear_discovery_cache, _discovery_cache
from app.auth.security import get_current_user
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

@pytest.mark.asyncio
async def test_csp_header_defaults_and_oidc_origin(monkeypatch):
    """Verify CSP connect-src dynamically incorporates OIDC issuer origin when configured."""
    # Test without OIDC_ISSUER
    monkeypatch.setattr(settings, "OIDC_ISSUER", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/health")
        csp = res.headers.get("Content-Security-Policy", "")
        assert "connect-src 'self'" in csp
        assert "auth.example.com" not in csp

    # Test with OIDC_ISSUER
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://auth.example.com/oauth/v2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/health")
        csp = res.headers.get("Content-Security-Policy", "")
        assert "connect-src 'self' https://auth.example.com" in csp

@pytest.mark.asyncio
async def test_oidc_discovery_caching(monkeypatch):
    """Verify OIDC discovery is cached in-memory and respects clear_discovery_cache."""
    clear_discovery_cache()
    issuer = "https://mock-idp.example.com"
    call_count = 0

    class MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"issuer": issuer, "jwks_uri": f"{issuer}/jwks.json"}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            nonlocal call_count
            call_count += 1
            return MockResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    # First fetch should make network call
    doc1 = await get_oidc_discovery(issuer)
    assert doc1["issuer"] == issuer
    assert call_count == 1
    assert issuer in _discovery_cache

    # Second fetch should hit cache without network call
    doc2 = await get_oidc_discovery(issuer)
    assert doc2 == doc1
    assert call_count == 1

    # Clearing cache should force new fetch
    clear_discovery_cache()
    assert issuer not in _discovery_cache
    doc3 = await get_oidc_discovery(issuer)
    assert call_count == 2

@pytest.mark.asyncio
async def test_demo_admin_role_distinction(monkeypatch):
    """Verify admin token assigns role='admin' rather than reviewer in demo mode."""
    monkeypatch.setattr(settings, "AUTH_MODE", "demo")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    admin_cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin")
    admin_user = await get_current_user(credentials=admin_cred)
    assert admin_user.role == "admin"
    assert admin_user.is_admin is True
    assert admin_user.is_reviewer is True  # Admins inherit reviewer capabilities
    assert admin_user.name == "System Administrator"

    rev_cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials="rev_lead")
    rev_user = await get_current_user(credentials=rev_cred)
    assert rev_user.role == "reviewer"
    assert rev_user.is_admin is False
    assert rev_user.is_reviewer is True

@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Verify GET /api/metrics returns valid operational stats and handles timedelta correctly."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/metrics", headers={"Authorization": "Bearer rev_lead"})
        assert res.status_code == 200
        data = res.json()
        assert "jobs" in data
        assert "refunds" in data
        assert "escalated_tickets" in data
        assert "overdue_tickets" in data
        assert "pending_approvals" in data
        assert "pending_reconciliations" in data

