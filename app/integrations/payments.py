"""Provider contracts normalize accepted versus completed refunds."""
import httpx
from sqlalchemy import select
from app.config import settings
from app.db.models import PaymentRecord, RefundOperation
from app.db.session import AsyncSessionLocal

class StripeGateway:
    async def issue_refund(self, idempotency_key, order_id, amount_minor, currency, reason=None):
        async with AsyncSessionLocal() as db:
            payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == order_id))).scalar_one()
            reference = payment.transaction_reference
        field = "payment_intent" if reference.startswith("pi_") else "charge"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post("https://api.stripe.com/v1/refunds",
                auth=(settings.STRIPE_SECRET_KEY, ""), headers={"Idempotency-Key": idempotency_key},
                data={field: reference, "amount": str(amount_minor), "metadata[operation_key]": idempotency_key})
            if response.status_code in (400, 402):
                return {"success": False, "status": "FAILED"}
            response.raise_for_status()
            return self.normalize(response.json())

    @staticmethod
    def normalize(body):
        status = {"succeeded": "SUCCEEDED", "failed": "FAILED", "canceled": "FAILED"}.get(body.get("status"), "PROCESSING")
        return {"success": True, "status": status, "gateway_reference": body["id"],
            "amount_minor": body["amount"], "currency": body["currency"].upper()}

    async def get_refund_status(self, key):
        async with AsyncSessionLocal() as db:
            op = (await db.execute(select(RefundOperation).where(RefundOperation.idempotency_key == key))).scalar_one()
            reference = op.gateway_reference
        if not reference:
            # Replaying the ORIGINAL key inside Stripe's retention window is safe; never invent a new key.
            return {"success": False, "error_code": "TRANSACTION_NOT_FOUND", "safe_to_resend": True}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"https://api.stripe.com/v1/refunds/{reference}", auth=(settings.STRIPE_SECRET_KEY, ""))
            response.raise_for_status()
            return self.normalize(response.json())

def get_payment_gateway():
    if settings.PAYMENT_PROVIDER == "stripe":
        if not settings.STRIPE_SECRET_KEY:
            raise ValueError("Stripe credentials are not configured.")
        if settings.STRIPE_SECRET_KEY.startswith(("sk_live_", "rk_live_")) and not settings.ALLOW_LIVE_PAYMENT_CREDENTIALS:
            raise RuntimeError("Live payment credentials are prohibited until explicit live-release authorization is granted.")
        return StripeGateway()
    from mock_services.payments.mock_payment_api import mock_payment_gateway
    return mock_payment_gateway
