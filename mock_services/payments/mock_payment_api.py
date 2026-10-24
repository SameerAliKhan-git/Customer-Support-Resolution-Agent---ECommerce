"""Mock Payment and Refund Provider API with realistic failure modes and idempotency enforcement."""
import asyncio
import time
import uuid
from typing import Dict, Any, Optional
from app.db.models import MockGatewayOperation
from app.db.session import AsyncSessionLocal

class MockPaymentGateway:
    """
    Simulates an external payment gateway (e.g., Stripe, Adyen).
    Implements:
    - Stable idempotency key tracking
    - Stored transaction state
    - Configurable network delays / timeouts
    - Payload mismatch detection on repeated idempotency keys
    - Status query for reconciliation
    """
    def __init__(self):
        # Maps idempotency_key -> {gateway_ref, amount_minor, currency, status, payload_hash, created_at}
        self.operations: Dict[str, Dict[str, Any]] = {}
        # Allows tests to force specific behavior
        self.forced_timeout_keys: set[str] = set()
        self.forced_failure_keys: set[str] = set()
        self.latency_seconds: float = 0.05

    def reset(self):
        self.operations.clear()
        self.forced_timeout_keys.clear()
        self.forced_failure_keys.clear()

    async def _load(self, key):
        async with AsyncSessionLocal() as db:
            saved = await db.get(MockGatewayOperation, key)
            if saved:
                self.operations[key] = saved.payload

    async def _save(self, key):
        async with AsyncSessionLocal() as db:
            await db.merge(MockGatewayOperation(id=key, payload=self.operations[key]))
            await db.commit()

    async def issue_refund(
        self,
        idempotency_key: str,
        order_id: str,
        amount_minor: int,
        currency: str = "USD",
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes an external refund request with strict idempotency contract.
        """
        payload_hash = f"{order_id}:{amount_minor}:{currency}"
        await self._load(idempotency_key)

        # Check existing operation with this key
        if idempotency_key in self.operations:
            existing = self.operations[idempotency_key]
            if existing["payload_hash"] != payload_hash:
                return {
                    "success": False,
                    "error_code": "IDEMPOTENCY_KEY_MISMATCH",
                    "retryable": False,
                    "message": f"Idempotency key '{idempotency_key}' was previously used with different parameters."
                }
            # Return same result
            return {
                "success": existing["status"] == "SUCCEEDED",
                "status": existing["status"],
                "gateway_reference": existing["gateway_reference"],
                "amount_minor": existing["amount_minor"],
                "currency": existing["currency"],
                "idempotent_replayed": True,
                "message": "Refund previously processed."
            }

        # Simulate network latency
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        # Check forced timeout condition
        if idempotency_key in self.forced_timeout_keys or idempotency_key.startswith("timeout_"):
            # The provider records the transaction internally, but the network connection times out!
            gateway_ref = f"gw_rf_{uuid.uuid4().hex[:10]}"
            self.operations[idempotency_key] = {
                "gateway_reference": gateway_ref,
                "order_id": order_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "status": "SUCCEEDED", # Succeeded on gateway, but caller never received 200 OK!
                "payload_hash": payload_hash,
                "created_at": time.time()
            }
            await self._save(idempotency_key)
            raise asyncio.TimeoutError("Connection to payment gateway timed out while awaiting response.")

        # Check forced failure condition
        if idempotency_key in self.forced_failure_keys or idempotency_key.startswith("fail_"):
            self.operations[idempotency_key] = {
                "gateway_reference": None,
                "order_id": order_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "status": "FAILED",
                "payload_hash": payload_hash,
                "created_at": time.time()
            }
            await self._save(idempotency_key)
            return {
                "success": False,
                "error_code": "CARD_NETWORK_DECLINED",
                "retryable": False,
                "message": "Payment provider rejected refund transaction (card closed or invalid merchant balance)."
            }

        # Normal successful disbursement
        gateway_ref = f"gw_rf_{uuid.uuid4().hex[:10]}"
        self.operations[idempotency_key] = {
            "gateway_reference": gateway_ref,
            "order_id": order_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "status": "SUCCEEDED",
            "payload_hash": payload_hash,
            "created_at": time.time()
        }

        await self._save(idempotency_key)
        return {
            "success": True,
            "status": "SUCCEEDED",
            "gateway_reference": gateway_ref,
            "amount_minor": amount_minor,
            "currency": currency,
            "idempotent_replayed": False,
            "message": "Refund processed successfully."
        }

    async def get_refund_status(self, idempotency_key: str) -> Dict[str, Any]:
        """
        Query provider state for reconciliation after timeouts or crashes.
        """
        await self._load(idempotency_key)
        if idempotency_key not in self.operations:
            return {
                "success": False,
                "error_code": "TRANSACTION_NOT_FOUND",
                "safe_to_resend": True,
                "message": f"No refund operation found for key '{idempotency_key}'."
            }
        
        op = self.operations[idempotency_key]
        return {
            "success": True,
            "status": op["status"],
            "gateway_reference": op["gateway_reference"],
            "amount_minor": op["amount_minor"],
            "currency": op["currency"],
            "created_at": op["created_at"]
        }

mock_payment_gateway = MockPaymentGateway()
