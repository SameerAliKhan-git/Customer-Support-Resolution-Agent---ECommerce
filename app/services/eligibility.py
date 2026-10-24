"""Revalidate approval bindings and financial facts without model involvement."""
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base, Order, ReturnRecord, PaymentRecord, PolicyChunk, Ticket

class ProposalBinding(Base):
    __tablename__ = "proposal_bindings"
    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))

async def fingerprint(db, proposal):
    order = await db.get(Order, proposal.order_id)
    returns = (await db.execute(select(ReturnRecord).where(ReturnRecord.order_id == proposal.order_id).order_by(ReturnRecord.id))).scalars().all()
    from app.policies.catalog import applicable_chunks
    chunks = await applicable_chunks(db, (order.delivery_date or order.order_date) if order else None)
    policy_hashes = sorted((c.policy_id, c.version, c.section, hashlib.sha256(c.content.encode()).hexdigest())
        for c in chunks if f"{c.policy_id}:{c.section}" in proposal.policy_refs)
    fields = {"policy_hashes": policy_hashes, "customer": proposal.customer_id, "order": proposal.order_id, "amount": proposal.amount_minor,
        "currency": proposal.currency, "reason": proposal.reason, "evidence": proposal.evidence_refs,
        "policies": proposal.policy_refs, "expires_at": proposal.expires_at.replace(tzinfo=None).isoformat(),
        "order_owner": order.customer_id if order else None, "order_total": order.total_amount_minor if order else None,
        "order_currency": order.currency if order else None,
        "returns": [(r.id, r.status, r.inspection_notes, r.created_at.replace(tzinfo=None).isoformat(),
            r.received_at.replace(tzinfo=None).isoformat() if r.received_at else None) for r in returns]}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

def expired(value):
    return value.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

REFUNDABLE_PAYMENT_STATUSES = {"CAPTURED", "PARTIALLY_REFUNDED"}
NON_REFUNDABLE_PAYMENT_STATUSES = {"VOIDED", "REFUNDED", "FAILED", "CANCELED", "EXPIRED"}

async def validate_refund(db, order_id, customer_id, amount_minor, currency, policy_refs, ticket_id=None, reserved=False):
    """The sole authoritative financial gate, used before proposal and execution."""
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
        raise ValueError("Refund amount must be a positive integer in minor units.")
    order = await db.get(Order, order_id, populate_existing=True)
    if not order or order.customer_id != customer_id:
        raise ValueError("Order does not belong to this customer.")
    if ticket_id:
        ticket = await db.get(Ticket, ticket_id)
        if not ticket or ticket.customer_id != customer_id or ticket.order_id not in (None, order_id):
            raise ValueError("Ticket does not belong to this customer and order.")
    payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == order_id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not payment or payment.customer_id != customer_id:
        raise ValueError("Payment record not found for this customer and order.")
    if payment.status not in REFUNDABLE_PAYMENT_STATUSES:
        raise ValueError(f"Payment status '{payment.status}' is not eligible for refund. Only captured or partially refunded payments can be refunded.")
    if payment.status in NON_REFUNDABLE_PAYMENT_STATUSES:
        raise ValueError(f"Payment status '{payment.status}' explicitly prohibits refunds.")
    if currency != order.currency or currency != payment.currency:
        raise ValueError("Refund currency must match order and payment.")
    available = payment.amount_minor - payment.refunded_amount_minor - payment.reserved_refund_minor
    if reserved:
        available += amount_minor
        if payment.reserved_refund_minor < amount_minor:
            raise ValueError("Refund reservation is missing.")
    if amount_minor > available or amount_minor > order.total_amount_minor:
        raise ValueError("Refund exceeds available refundable balance.")
    from app.policies.catalog import applicable_chunks
    chunks = await applicable_chunks(db, order.delivery_date or order.order_date)
    refs = {f"{chunk.policy_id}:{chunk.section}": chunk for chunk in chunks}
    if not policy_refs or any(ref not in refs for ref in policy_refs):
        raise ValueError("Applicable, published policy evidence is required.")
    is_damage = any(ref.startswith("damaged_goods_policy_") for ref in policy_refs)
    if not is_damage and not any(ref.startswith("refund_policy_") for ref in policy_refs):
        raise ValueError("A refund eligibility policy is required.")
    returns = (await db.execute(select(ReturnRecord).where(ReturnRecord.order_id == order_id)
        .order_by(ReturnRecord.created_at.desc()))).scalars().all()
    returned = returns[0] if returns else None
    inspected = returned and returned.customer_id == customer_id and returned.status == "INSPECTION_PASSED"
    if is_damage:
        if not order.delivery_date:
            raise ValueError("Confirmed delivery is required for a damage claim.")
        age = (datetime.utcnow() - order.delivery_date.replace(tzinfo=None)).total_seconds() / 86400
        if not 0 <= age < 8 or amount_minor > 50000 or (amount_minor > 10000 and not inspected):
            raise ValueError("Damage claim requires specialist review or verified evidence.")
    else:
        if not inspected or not returned.received_at or not order.delivery_date:
            raise ValueError("Warehouse receipt and successful inspection are required.")
        elapsed = (returned.created_at.replace(tzinfo=None) - order.delivery_date.replace(tzinfo=None)).total_seconds() / 86400
        if not 0 <= elapsed < 31:
            raise ValueError("Return was initiated outside the 30-day return window.")
    return payment
