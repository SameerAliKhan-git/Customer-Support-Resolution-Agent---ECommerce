"""Approval service managing refund proposals, human reviews, and expiration."""
import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.config import settings
from app.db.models import RefundProposal, Approval, generate_id, Ticket, PaymentRecord, ReturnRecord, PolicyChunk
from app.services.audit_service import audit_service
from app.services.eligibility import ProposalBinding, fingerprint
from app.services.locks import serialized

class ApprovalService:
    @staticmethod
    async def create_proposal(
        db: AsyncSession,
        ticket_id: str,
        order_id: str,
        customer_id: str,
        amount_minor: int,
        reason: str,
        evidence_refs: List[str],
        policy_refs: List[str],
        missing_information: Optional[List[str]] = None,
        currency: str = "USD",
        supersedes_proposal_id: Optional[str] = None
    ) -> RefundProposal:
        """
        Creates an immutable refund proposal and binds a pending approval record.
        If supersedes_proposal_id is provided, the old proposal must be in a terminal state (DECLINED, EXPIRED, EXECUTED).
        """
        from app.services.eligibility import validate_refund
        await db.execute(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(hours=settings.PROPOSAL_EXPIRY_HOURS)
        
        # Handle superseded proposal
        if supersedes_proposal_id:
            old_proposal = await db.get(RefundProposal, supersedes_proposal_id)
            if not old_proposal:
                raise ValueError(f"Superseded proposal '{supersedes_proposal_id}' not found.")
            if old_proposal.status not in ("DECLINED", "EXPIRED", "EXECUTED"):
                raise ValueError(f"Cannot supersede proposal in status '{old_proposal.status}'. Must be DECLINED, EXPIRED, or EXECUTED.")
            if old_proposal.ticket_id != ticket_id or old_proposal.order_id != order_id:
                raise ValueError("Superseded proposal must belong to the same ticket and order.")
        else:
            # Check for existing active proposal on same ticket/order
            previous = (await db.execute(select(RefundProposal).where(
                RefundProposal.ticket_id == ticket_id, RefundProposal.order_id == order_id,
                RefundProposal.status.in_(["PENDING", "APPROVED"])
            ))).scalars().first()
            if previous and previous.expires_at.replace(tzinfo=datetime.timezone.utc) <= now:
                from app.db.models import RefundOperation
                operation = (await db.execute(select(RefundOperation).where(RefundOperation.proposal_id == previous.id))).scalar_one_or_none()
                if operation:
                    raise ValueError("An existing operation must be reconciled before proposing another refund.")
                previous.status = "EXPIRED"
                old_approval = (await db.execute(select(Approval).where(Approval.proposal_id == previous.id))).scalar_one()
                old_approval.decision = "EXPIRED"
                await db.execute(update(PaymentRecord).where(PaymentRecord.order_id == order_id).values(
                    reserved_refund_minor=PaymentRecord.reserved_refund_minor - previous.amount_minor))
                await db.commit()
                previous = None
            if previous:
                if (previous.customer_id, previous.amount_minor, previous.currency, previous.reason, previous.policy_refs) == (customer_id, amount_minor, currency, reason, policy_refs):
                    return previous
                raise ValueError("This ticket already has a different active proposal requiring review.")

        payment = await validate_refund(db, order_id, customer_id, amount_minor, currency, policy_refs, ticket_id)
        # Reserve the amount in payment record to prevent double-proposing
        reserved = await db.execute(update(PaymentRecord).where(
            PaymentRecord.id == payment.id,
            PaymentRecord.amount_minor - PaymentRecord.refunded_amount_minor - PaymentRecord.reserved_refund_minor >= amount_minor,
        ).values(reserved_refund_minor=PaymentRecord.reserved_refund_minor + amount_minor))
        if reserved.rowcount != 1:
            await db.rollback()
            raise ValueError("Refund balance is already reserved.")

        proposal = RefundProposal(
            id=generate_id("prop"),
            ticket_id=ticket_id,
            order_id=order_id,
            customer_id=customer_id,
            amount_minor=amount_minor,
            currency=currency,
            reason=reason,
            evidence_refs=evidence_refs,
            policy_refs=policy_refs,
            missing_information=missing_information or [],
            status="PENDING",
            supersedes_proposal_id=supersedes_proposal_id,
            expires_at=expires_at,
            created_at=now
        )
        db.add(proposal)
        await db.flush()

        db.add(ProposalBinding(proposal_id=proposal.id, fingerprint=await fingerprint(db, proposal)))

        approval = Approval(
            id=generate_id("appr"),
            proposal_id=proposal.id,
            decision="PENDING",
            created_at=now
        )
        db.add(approval)
        await db.flush()

        await audit_service.log_event(
            db=db,
            entity_type="PROPOSAL",
            entity_id=proposal.id,
            actor_type="AGENT",
            actor_id="resolution_agent",
            action="PROPOSAL_CREATED",
            details={
                "order_id": order_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "approval_id": approval.id,
                "policy_refs": policy_refs,
                "supersedes_proposal_id": supersedes_proposal_id
            }
        )
        await db.commit()
        return proposal

    @staticmethod
    @serialized
    async def decide_approval(
        db: AsyncSession,
        approval_id: str,
        decision: str, # "APPROVED" or "REJECTED"
        reviewer_id: str,
        reviewer_name: str,
        decision_notes: Optional[str] = None
    ) -> Approval:
        if decision not in ("APPROVED", "REJECTED"):
            raise ValueError("Invalid reviewer decision.")
        stmt = select(Approval).where(Approval.id == approval_id).with_for_update()
        res = await db.execute(stmt)
        approval = res.scalar_one_or_none()
        if not approval:
            raise ValueError(f"Approval record '{approval_id}' not found.")
        if approval.decision != "PENDING":
            raise ValueError("Approval has already been decided; decisions are immutable.")
        
        prop_stmt = select(RefundProposal).where(RefundProposal.id == approval.proposal_id)
        prop_res = await db.execute(prop_stmt)
        proposal = prop_res.scalar_one_or_none()
        if not proposal:
            raise ValueError(f"Proposal '{approval.proposal_id}' not found.")

        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Check expiration
        # Ensure proposal.expires_at is timezone-aware for comparison
        expires_at = proposal.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
            
        if expires_at < now:
            approval.decision = "EXPIRED"
            proposal.status = "EXPIRED"
            # Release reservation on payment
            p_stmt = select(PaymentRecord).where(PaymentRecord.order_id == proposal.order_id).with_for_update()
            p_res = await db.execute(p_stmt)
            pay = p_res.scalar_one_or_none()
            if pay:
                pay.reserved_refund_minor = max(0, pay.reserved_refund_minor - proposal.amount_minor)
            await db.commit()
            raise ValueError(f"Proposal '{proposal.id}' has expired. Fresh proposal and approval required.")

        approval.decision = decision
        approval.reviewer_id = reviewer_id
        approval.reviewer_name = reviewer_name
        approval.decision_notes = decision_notes
        approval.decided_at = now

        proposal.status = decision # "APPROVED" or "REJECTED"

        if decision == "REJECTED":
            # Release reserved refund minor
            p_stmt = select(PaymentRecord).where(PaymentRecord.order_id == proposal.order_id).with_for_update()
            p_res = await db.execute(p_stmt)
            pay = p_res.scalar_one_or_none()
            if pay:
                pay.reserved_refund_minor = max(0, pay.reserved_refund_minor - proposal.amount_minor)

        await audit_service.log_event(
            db=db,
            entity_type="APPROVAL",
            entity_id=approval.id,
            actor_type="REVIEWER",
            actor_id=reviewer_id,
            action=f"APPROVAL_{decision}",
            details={"reviewer_name": reviewer_name, "notes": decision_notes, "proposal_id": proposal.id}
        )
        await db.commit()
        return approval

    @staticmethod
    @serialized
    async def list_pending_approvals(db: AsyncSession) -> List[Dict[str, Any]]:
        stmt = (
            select(Approval, RefundProposal)
            .join(RefundProposal, Approval.proposal_id == RefundProposal.id)
            .where(Approval.decision == "PENDING")
            .order_by(Approval.created_at.desc()).with_for_update()
        )
        res = await db.execute(stmt)
        items = []
        for appr, prop in res.all():
            expires = prop.expires_at.replace(tzinfo=datetime.timezone.utc)
            if expires <= datetime.datetime.now(datetime.timezone.utc):
                appr.decision = "EXPIRED"
                prop.status = "EXPIRED"
                payment = (await db.execute(select(PaymentRecord).where(PaymentRecord.order_id == prop.order_id).with_for_update())).scalar_one_or_none()
                if payment:
                    payment.reserved_refund_minor = max(0, payment.reserved_refund_minor - prop.amount_minor)
                continue
            items.append({
                "approval_id": appr.id,
                "proposal_id": prop.id,
                "ticket_id": prop.ticket_id,
                "order_id": prop.order_id,
                "customer_id": prop.customer_id,
                "amount_minor": prop.amount_minor,
                "currency": prop.currency,
                "reason": prop.reason,
                "evidence_refs": prop.evidence_refs,
                "policy_refs": prop.policy_refs,
                "missing_information": prop.missing_information,
                "status": appr.decision,
                "created_at": appr.created_at.isoformat(),
                "expires_at": prop.expires_at.isoformat(),
            })
        await db.commit()
        return items

approval_service = ApprovalService()
