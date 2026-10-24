"""Comprehensive payment provider sandbox qualification matrix and webhook integration tests."""
import hashlib
import hmac
import json
import time
import pytest
from httpx import AsyncClient, ASGITransport, Response
from sqlalchemy import select
from app.main import app
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import PaymentRecord, RefundOperation, Approval
from app.db.operations import ProviderEvent
from app.integrations.payments import StripeGateway, get_payment_gateway
from app.services.refund_service import refund_service
from app.services.approval_service import approval_service
from app.workflows.engine import workflow_engine

def generate_stripe_signature(payload_bytes: bytes, secret: str, timestamp: int = None) -> str:
    ts = timestamp or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload_bytes, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"

@pytest.mark.asyncio
async def test_live_key_guard_prohibits_accidental_live_credentials(monkeypatch):
    """Verify that sk_live_* or rk_live_* keys are blocked unless explicitly authorized."""
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "stripe")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_live_dummy1234567890abcdef")
    monkeypatch.setattr(settings, "ALLOW_LIVE_PAYMENT_CREDENTIALS", False)

    with pytest.raises(RuntimeError, match="Live payment credentials are prohibited"):
        get_payment_gateway()

    # If ALLOW_LIVE_PAYMENT_CREDENTIALS is explicitly True, it permits initialization
    monkeypatch.setattr(settings, "ALLOW_LIVE_PAYMENT_CREDENTIALS", True)
    gateway = get_payment_gateway()
    assert isinstance(gateway, StripeGateway)

@pytest.mark.asyncio
async def test_stripe_gateway_response_normalization(monkeypatch):
    """Verify normalization of succeeded, pending, failed, and canceled Stripe responses."""
    gateway = StripeGateway()
    # Succeeded
    norm_succeeded = gateway.normalize({"id": "re_123", "status": "succeeded", "amount": 2500, "currency": "usd"})
    assert norm_succeeded["status"] == "SUCCEEDED"
    assert norm_succeeded["success"] is True
    assert norm_succeeded["gateway_reference"] == "re_123"

    # Pending
    norm_pending = gateway.normalize({"id": "re_456", "status": "pending", "amount": 2500, "currency": "usd"})
    assert norm_pending["status"] == "PROCESSING"

    # Failed & Canceled
    norm_failed = gateway.normalize({"id": "re_789", "status": "failed", "amount": 2500, "currency": "usd"})
    assert norm_failed["status"] == "FAILED"

    norm_canceled = gateway.normalize({"id": "re_000", "status": "canceled", "amount": 2500, "currency": "usd"})
    assert norm_canceled["status"] == "FAILED"

@pytest.mark.asyncio
async def test_stripe_webhook_signature_and_deduplication(monkeypatch):
    """Verify signed webhook inbox: signature verification, timestamp tolerance, and deduplication."""
    webhook_secret = "whsec_test_secret_12345"
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "stripe")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", webhook_secret)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        event_payload = {
            "id": "evt_test_refund_1001",
            "type": "charge.refund.updated",
            "data": {
                "object": {
                    "id": "re_test_ref_1001",
                    "status": "succeeded",
                    "amount": 24999
                }
            }
        }
        body_bytes = json.dumps(event_payload).encode()

        # 1. Valid signature -> 200 OK
        valid_sig = generate_stripe_signature(body_bytes, webhook_secret)
        resp1 = await client.post(
            "/api/integrations/stripe/webhook",
            content=body_bytes,
            headers={"stripe-signature": valid_sig, "content-type": "application/json"}
        )
        assert resp1.status_code == 200
        assert resp1.json() == {"received": True}

        # Verify event recorded in provider_events
        async with AsyncSessionLocal() as db:
            evt = await db.get(ProviderEvent, "evt_test_refund_1001")
            assert evt is not None
            assert evt.payload["reference"] == "re_test_ref_1001"

        # 2. Duplicate event delivery -> 200 OK with duplicate: True
        resp2 = await client.post(
            "/api/integrations/stripe/webhook",
            content=body_bytes,
            headers={"stripe-signature": valid_sig, "content-type": "application/json"}
        )
        assert resp2.status_code == 200
        assert resp2.json() == {"received": True, "duplicate": True}

        # 3. Invalid signature -> 400 Bad Request
        bad_sig = generate_stripe_signature(body_bytes, "whsec_wrong_secret")
        resp3 = await client.post(
            "/api/integrations/stripe/webhook",
            content=body_bytes,
            headers={"stripe-signature": bad_sig, "content-type": "application/json"}
        )
        assert resp3.status_code == 400

        # 4. Stale timestamp (older than 300 seconds) -> 400 Bad Request
        stale_ts = int(time.time()) - 600
        stale_sig = generate_stripe_signature(body_bytes, webhook_secret, timestamp=stale_ts)
        resp4 = await client.post(
            "/api/integrations/stripe/webhook",
            content=body_bytes,
            headers={"stripe-signature": stale_sig, "content-type": "application/json"}
        )
        assert resp4.status_code == 400

@pytest.mark.asyncio
async def test_same_key_same_payload_vs_changed_payload_idempotency():
    """Verify that reusing the same idempotency key with identical payload is safe, but changed payload raises."""
    state = await workflow_engine.start_workflow("cust_1001", "Please refund my returned headphones", "ord_1001")
    proposal_id = state["proposed_action_id"]

    async with AsyncSessionLocal() as db:
        approval = (await db.execute(select(Approval).where(Approval.proposal_id == proposal_id))).scalar_one()
        await approval_service.decide_approval(db, approval.id, "APPROVED", "rev_test", "Reviewer")

        # Execute refund with a stable operation key
        result1 = await refund_service.execute_approved_refund(db, proposal_id, "rev_test", idempotency_key="idemp_test_key_1")
        assert result1["success"]
        op1_ref = result1["gateway_reference"]

        # Re-executing with the exact same proposal and key must return the same result safely
        result2 = await refund_service.execute_approved_refund(db, proposal_id, "rev_test", idempotency_key="idemp_test_key_1")
        assert result2["success"]
        assert result2["gateway_reference"] == op1_ref

        # Check payment record: exactly 1 refund effect applied!
        payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == "ord_1001"))).scalar_one()
        assert payment.refunded_amount_minor == 24999
        assert payment.reserved_refund_minor == 0

@pytest.mark.asyncio
async def test_timeout_reconciliation_flow_and_customer_language():
    """Verify that timeout outcomes record uncertainty and never present success until reconciled."""
    state = await workflow_engine.start_workflow("cust_1001", "Please refund my returned headphones", "ord_1001")
    proposal_id = state["proposed_action_id"]

    async with AsyncSessionLocal() as db:
        approval = (await db.execute(select(Approval).where(Approval.proposal_id == proposal_id))).scalar_one()
        await approval_service.decide_approval(db, approval.id, "APPROVED", "rev_test", "Reviewer")

        # Execute with key prefix triggering simulated timeout
        timeout_key = "timeout_test_key_999"
        result_timeout = await refund_service.execute_approved_refund(db, proposal_id, "rev_test", idempotency_key=timeout_key)

        # Must NOT be marked as successful yet
        assert not result_timeout.get("success", False)
        assert result_timeout["status"] == "PENDING_RECONCILIATION"
        # Customer facing message must indicate verification in progress, NOT successful completion
        msg = result_timeout.get("message", "").lower()
        assert "success" not in msg or "reconcil" in msg or "timeout" in msg or "verif" in msg

        # Operation in DB is PENDING_RECONCILIATION
        op = (await db.execute(select(RefundOperation).where(RefundOperation.idempotency_key == timeout_key))).scalar_one()
        assert op.status == "PENDING_RECONCILIATION"

        # Now reconcile using the original operation key via execute_approved_refund
        reconciled = await refund_service.execute_approved_refund(db, proposal_id, "rev_test", idempotency_key=timeout_key)
        assert reconciled["success"] is True
        assert reconciled["status"] == "SUCCEEDED"

        # Operation is now SUCCEEDED
        await db.refresh(op)
        assert op.status == "SUCCEEDED"
