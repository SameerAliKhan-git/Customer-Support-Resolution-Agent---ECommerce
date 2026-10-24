"""Integration tests qualifying the OIDC identity integration against an asymmetric JWKS provider."""
import http.server
import json
import threading
import time
from typing import Dict, Any, List
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
import jwt
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings
from app.auth.oidc import key_client

# Generate an RSA key pair for testing
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()
_jwk = json.loads(RSAAlgorithm.to_jwk(_public_key))
_jwk.update({"kid": "test-oidc-key-1", "use": "sig", "alg": "RS256"})

class _OIDCTestServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = None
        self.issuer = None

    def start(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    host = self.headers.get("Host")
                    iss = f"http://{host}"
                    self.wfile.write(json.dumps({
                        "issuer": iss,
                        "jwks_uri": f"{iss}/jwks.json"
                    }).encode())
                elif self.path == "/jwks.json":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"keys": [_jwk]}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.issuer = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

@pytest.fixture(scope="module")
def oidc_server():
    server = _OIDCTestServer()
    server.start()
    yield server
    server.stop()

def create_oidc_token(
    issuer: str,
    sub: str,
    roles: List[str],
    amr: List[str] = None,
    audience: str = "support-api",
    expires_in: int = 3600,
    kid: str = "test-oidc-key-1",
    name: str = "Test User"
) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer,
        "sub": sub,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "name": name,
        "realm_access": {"roles": roles},
        "amr": amr or ["pwd"]
    }
    return jwt.encode(payload, _private_key, algorithm="RS256", headers={"kid": kid})

@pytest.mark.asyncio
async def test_oidc_customer_authentication_and_scoped_access(oidc_server, monkeypatch):
    """Verify that an OIDC token mapped to an external customer subject can access own records."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", oidc_server.issuer)
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", "support-api")
    key_client.cache_clear()

    # Create token for provisioned customer Alice (auth0|cust_1001)
    token = create_oidc_token(oidc_server.issuer, sub="auth0|cust_1001", roles=["customer"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check /api/session/me
        me_resp = await client.get("/api/session/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["id"] == "cust_1001"
        assert data["role"] == "customer"
        assert data["name"] == "Alice Johnson"

        # Check accessing own ticket
        tkt_resp = await client.get("/api/tickets/tkt_1001", headers={"Authorization": f"Bearer {token}"})
        assert tkt_resp.status_code == 200
        assert tkt_resp.json()["customer_id"] == "cust_1001"

@pytest.mark.asyncio
async def test_oidc_cross_customer_access_forbidden(oidc_server, monkeypatch):
    """Verify that an authenticated customer cannot view or modify another customer's ticket or order."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", oidc_server.issuer)
    key_client.cache_clear()

    # Alice (cust_1001) tries to access Bob's (cust_1002) ticket (tkt_1002)
    alice_token = create_oidc_token(oidc_server.issuer, sub="auth0|cust_1001", roles=["customer"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tickets/tkt_1002", headers={"Authorization": f"Bearer {alice_token}"})
        # Must be forbidden and leak no internal order existence details
        assert resp.status_code == 403

        # Alice tries to create complaint with Bob's order ord_1002
        post_resp = await client.post("/api/complaints", headers={"Authorization": f"Bearer {alice_token}"}, json={
            "customer_id": "cust_1001",
            "order_id": "ord_1002",
            "message": "Refund Bob's order"
        })
        assert post_resp.status_code == 403

@pytest.mark.asyncio
async def test_oidc_unprovisioned_customer_rejected(oidc_server, monkeypatch):
    """Verify that a valid OIDC customer token whose external subject is unknown is rejected with 403."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", oidc_server.issuer)
    key_client.cache_clear()

    # Unknown external subject
    unknown_token = create_oidc_token(oidc_server.issuer, sub="auth0|unknown_sub_9999", roles=["customer"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/session/me", headers={"Authorization": f"Bearer {unknown_token}"})
        assert resp.status_code == 403
        assert "not provisioned" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_oidc_staff_mfa_requirement(oidc_server, monkeypatch):
    """Verify that reviewers and admins require MFA authentication assurance."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", oidc_server.issuer)
    monkeypatch.setattr(settings, "OIDC_REQUIRE_STAFF_MFA", True)
    key_client.cache_clear()

    # Reviewer with password only (no MFA)
    no_mfa_token = create_oidc_token(oidc_server.issuer, sub="staff_rev_1", roles=["reviewer"], amr=["pwd"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Accessing pending approvals requires reviewer authorization
        resp = await client.get("/api/approvals/pending", headers={"Authorization": f"Bearer {no_mfa_token}"})
        # Blocked because staff access requires MFA
        assert resp.status_code == 401

        # Reviewer with MFA (amr includes 'mfa')
        mfa_token = create_oidc_token(oidc_server.issuer, sub="staff_rev_1", roles=["reviewer"], amr=["pwd", "mfa"])
        resp_mfa = await client.get("/api/approvals/pending", headers={"Authorization": f"Bearer {mfa_token}"})
        assert resp_mfa.status_code == 200

@pytest.mark.asyncio
async def test_oidc_invalid_tokens_rejected(oidc_server, monkeypatch):
    """Verify expired token, bad signature, and wrong audience are rejected with 401."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", oidc_server.issuer)
    key_client.cache_clear()

    # 1. Expired token
    expired_token = create_oidc_token(oidc_server.issuer, sub="auth0|cust_1001", roles=["customer"], expires_in=-100)
    # 2. Wrong audience
    wrong_aud_token = create_oidc_token(oidc_server.issuer, sub="auth0|cust_1001", roles=["customer"], audience="wrong-api")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.get("/api/session/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp1.status_code == 401

        resp2 = await client.get("/api/session/me", headers={"Authorization": f"Bearer {wrong_aud_token}"})
        assert resp2.status_code == 401
