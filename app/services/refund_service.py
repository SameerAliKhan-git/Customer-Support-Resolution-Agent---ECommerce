"""Transactional refund execution with database leases and recoverable outcomes."""
import asyncio
import datetime
from sqlalchemy import select
from app.db.models import RefundProposal, Approval, RefundOperation, PaymentRecord, generate_id
from app.db.session import AsyncSessionLocal
from app.services.audit_service import audit_service
from app.services.eligibility import ProposalBinding, fingerprint, expired, validate_refund
from app.services.leases import lease
from app.services.locks import serialized
from app.integrations.payments import get_payment_gateway

TERMINAL = {"SUCCEEDED", "FAILED", "DECLINED"}
RECOVERABLE = {"CLAIMED", "SENDING", "PROCESSING", "PENDING_RECONCILIATION", "UNKNOWN"}

def result(op, replay=False):
    return {"success": op.status == "SUCCEEDED", "status": op.status, "operation_id": op.id,
        "gateway_reference": op.gateway_reference, "amount_minor": op.amount_minor, "currency": op.currency,
        "idempotent_replayed": replay, "retryable": op.status in RECOVERABLE,
        "message": "Refund verified." if op.status == "SUCCEEDED" else (op.error_message or "Refund outcome is pending verification.")}

class RefundService:
    @staticmethod
    @serialized
    async def execute_approved_refund(db, proposal_id, reviewer_id, idempotency_key=None):
        await db.commit()
        async with lease("refund:" + proposal_id) as owner:
            if not owner:
                return {"success": False, "status": "PROCESSING", "retryable": True, "message": "Another worker owns this operation."}
            try:
                return await RefundService._execute(db, proposal_id, reviewer_id, idempotency_key)
            finally:
                await db.rollback()

    @staticmethod
    async def _execute(db, proposal_id, reviewer_id, idempotency_key=None):
        proposal = await db.get(RefundProposal, proposal_id, populate_existing=True)
        if not proposal:
            return {"success": False, "status": "FAILED", "message": "Proposal not found."}
        approval = (await db.execute(select(Approval).where(Approval.proposal_id == proposal_id))).scalar_one_or_none()
        if not approval or approval.decision != "APPROVED":
            return {"success": False, "status": "FAILED", "error_code": "UNAUTHORIZED_ACTION", "message": "A stored human approval is required."}
        op = (await db.execute(select(RefundOperation).where(RefundOperation.proposal_id == proposal_id))).scalar_one_or_none()
        if op:
            if op.status in TERMINAL:
                return result(op, True)
            return await RefundService._recover(db, op, reviewer_id)
        binding = await db.get(ProposalBinding, proposal_id)
        try:
            if proposal.status != "APPROVED" or expired(proposal.expires_at) or not binding or binding.fingerprint != await fingerprint(db, proposal):
                raise ValueError("Approval expired or material facts changed; fresh review is required.")
            await validate_refund(db, proposal.order_id, proposal.customer_id, proposal.amount_minor,
                proposal.currency, proposal.policy_refs, proposal.ticket_id, reserved=True)
        except ValueError as exc:
            pay = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == proposal.order_id).with_for_update())).scalar_one_or_none()
            if pay and proposal.status == "APPROVED":
                pay.reserved_refund_minor = max(0, pay.reserved_refund_minor - proposal.amount_minor)
            proposal.status = "INVALIDATED"
            await db.commit()
            return {"success": False, "status": "FAILED", "message": str(exc)}
        op = RefundOperation(id=generate_id("op"), proposal_id=proposal_id, order_id=proposal.order_id,
            customer_id=proposal.customer_id, amount_minor=proposal.amount_minor, currency=proposal.currency,
            idempotency_key=idempotency_key or f"idem_rf_{proposal_id}", status="CLAIMED", attempt_count=1,
            request_payload={"reason": proposal.reason})
        db.add(op)
        await db.commit()
        return await RefundService._send(db, op, proposal.reason, reviewer_id)

    @staticmethod
    async def _send(db, op, reason, actor):
        gateway = get_payment_gateway()
        op.status = "SENDING"
        op.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()
        try:
            from app.services.telemetry import add
            add("provider_calls")
            response = await gateway.issue_refund(idempotency_key=op.idempotency_key, order_id=op.order_id,
                amount_minor=op.amount_minor, currency=op.currency, reason=reason)
        except Exception as exc:
            op.status = "PENDING_RECONCILIATION"
            op.error_code = "GATEWAY_TIMEOUT" if isinstance(exc, asyncio.TimeoutError) else "PROVIDER_UNCERTAIN"
            op.error_message = "Provider outcome is uncertain; original operation will be reconciled."
            op.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await audit_service.log_event(db, "REFUND_OPERATION", op.id, "SYSTEM", actor,
                "REFUND_TIMEOUT_RECONCILIATION_REQUIRED" if isinstance(exc, asyncio.TimeoutError) else "REFUND_OUTCOME_UNKNOWN",
                {"order_id": op.order_id})
            await db.commit()
            return result(op)
        return await RefundService._apply(db, op.id, response, actor)

    @staticmethod
    async def _recover(db, op, actor):
        if op.attempt_count >= 8:
            op.error_code = "MANUAL_REVIEW_REQUIRED"
            op.error_message = "Automatic recovery limit reached; specialist review required."
            op.status = "PENDING_RECONCILIATION"
            await db.commit()
            output = result(op)
            output.update(status="MANUAL_REVIEW_REQUIRED", retryable=False)
            return output
        key = op.idempotency_key
        await db.commit()
        from app.services.telemetry import add
        add("provider_calls")
        response = await get_payment_gateway().get_refund_status(key)
        if response.get("success") and response.get("status") in ("SUCCEEDED", "FAILED", "CANCELED"):
            return await RefundService._apply(db, op.id, response, actor, reconciled=True)
        created_tz = op.created_at if op.created_at.tzinfo else op.created_at.replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - created_tz).total_seconds()
        if response.get("error_code") == "TRANSACTION_NOT_FOUND" and response.get("safe_to_resend") and age < 23 * 3600:
            if op.status not in ("SENDING", "CLAIMED", "PROCESSING"):
                op.status = "PENDING_RECONCILIATION"
                op.error_message = "Provider operation not found but original state was not CLAIMED/SENDING/PROCESSING; manual reconciliation required."
                op.attempt_count += 1
                await db.commit()
                return result(op)
            op.attempt_count += 1
            await db.commit()
            if not op.request_payload.get("reason"):
                op.error_message = "Original provider payload is missing; manual reconciliation is required."
                await db.commit()
                return result(op)
            return await RefundService._send(db, op, op.request_payload["reason"], actor)
        op.status = "PENDING_RECONCILIATION"
        op.attempt_count += 1
        op.error_message = "Provider outcome has not been established; no new payment key was created."
        await db.commit()
        return result(op)

    @staticmethod
    async def _apply(db, operation_id, response, actor, reconciled=False):
        op = (await db.execute(select(RefundOperation).where(RefundOperation.id == operation_id)
            .with_for_update().execution_options(populate_existing=True))).scalar_one()
        if op.status in TERMINAL:
            return result(op, True)
        remote = response.get("status", "FAILED" if not response.get("success") else "PROCESSING")
        if response.get("amount_minor", op.amount_minor) != op.amount_minor or response.get("currency", op.currency).upper() != op.currency.upper():
            remote = "UNKNOWN"
        if remote == "SUCCEEDED" and not response.get("gateway_reference"):
            remote = "UNKNOWN"
        proposal = await db.get(RefundProposal, op.proposal_id)
        payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == op.order_id)
            .with_for_update().execution_options(populate_existing=True))).scalar_one()
        op.gateway_reference = response.get("gateway_reference") or op.gateway_reference
        op.updated_at = datetime.datetime.now(datetime.timezone.utc)
        if remote == "SUCCEEDED":
            if payment.refunded_amount_minor + op.amount_minor > payment.amount_minor or payment.reserved_refund_minor < op.amount_minor:
                op.status = "PENDING_RECONCILIATION"
                op.error_code = "LEDGER_REVIEW_REQUIRED"
                op.error_message = "Provider succeeded but ledger invariants require manual review."
                await db.commit()
                return result(op)
            payment.refunded_amount_minor += op.amount_minor
            payment.reserved_refund_minor -= op.amount_minor
            payment.status = "REFUNDED" if payment.refunded_amount_minor == payment.amount_minor else "PARTIALLY_REFUNDED"
            op.status, proposal.status = "SUCCEEDED", "EXECUTED"
            op.error_code = op.error_message = None
            action = "REFUND_RECONCILED_SUCCESS" if reconciled else "REFUND_SUCCEEDED"
        elif remote in ("FAILED", "CANCELED"):
            payment.reserved_refund_minor = max(0, payment.reserved_refund_minor - op.amount_minor)
            op.status = "DECLINED"
            proposal.status = "DECLINED"
            op.error_message = "Payment provider declined this operation. A replacement proposal requires fresh approval."
            action = "REFUND_DECLINED"
        else:
            op.status = "PENDING_RECONCILIATION"
            op.error_message = "The provider accepted or is checking the request; completion is not confirmed."
            action = "REFUND_PROCESSING"
        await audit_service.log_event(db, "REFUND_OPERATION", op.id, "SYSTEM", actor, action,
            {"order_id": op.order_id, "amount_minor": op.amount_minor, "gateway_reference": op.gateway_reference})
        await db.commit()
        return result(op)

    @staticmethod
    @serialized
    async def reconcile_refund(db, idempotency_key):
        op = (await db.execute(select(RefundOperation).where(RefundOperation.idempotency_key == idempotency_key))).scalar_one_or_none()
        if not op:
            return {"success": False, "status": "FAILED", "message": "Operation not found."}
        proposal_id = op.proposal_id
        await db.commit()
        async with lease("refund:" + proposal_id) as owner:
            if not owner:
                return {"success": False, "status": "PROCESSING", "retryable": True}
            try:
                if op.status in TERMINAL:
                    return result(op, True)
                return await RefundService._recover(db, op, "reconciliation_worker")
            finally:
                await db.rollback()

refund_service = RefundService()
