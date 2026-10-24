"""Typed write tools for proposing refunds, executing approved refunds, and updating tickets."""
from app.services.telemetry import tool
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.approval_service import approval_service
from app.services.refund_service import refund_service
from app.services.ticket_service import ticket_service

class WriteTools:
    """
    Write tools. Strictly separates proposal generation from privileged financial disbursement.
    """
    @staticmethod
    @tool
    async def create_refund_proposal(
        ticket_id: str,
        order_id: str,
        authenticated_customer_id: str,
        amount_minor: int,
        reason: str,
        evidence_refs: List[str],
        policy_refs: List[str],
        db: AsyncSession,
        missing_information: Optional[List[str]] = None,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """
        Creates an immutable refund proposal awaiting reviewer approval.
        Does NOT move any funds.
        """
        try:
            proposal = await approval_service.create_proposal(
                db=db,
                ticket_id=ticket_id,
                order_id=order_id,
                customer_id=authenticated_customer_id,
                amount_minor=amount_minor,
                reason=reason,
                evidence_refs=evidence_refs,
                policy_refs=policy_refs,
                missing_information=missing_information,
                currency=currency
            )
            from sqlalchemy import select
            from app.db.models import Approval
            approval_id = (await db.execute(select(Approval.id).where(Approval.proposal_id == proposal.id))).scalar_one()
            return {
                "success": True,
                "approval_id": approval_id,
                "proposal_id": proposal.id,
                "status": proposal.status,
                "amount_minor": proposal.amount_minor,
                "currency": proposal.currency,
                "expires_at": proposal.expires_at.isoformat(),
                "requires_approval": True,
                "message": "Refund proposal created successfully and submitted to support review queue."
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": "PROPOSAL_CREATION_FAILED",
                "retryable": False,
                "message": str(e)
            }

    @staticmethod
    @tool
    async def execute_approved_refund(
        proposal_id: str,
        reviewer_id: str,
        db: AsyncSession,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Privileged operation: Executes an approved proposal.
        Requires reviewer identity.
        """
        return await refund_service.execute_approved_refund(
            db=db,
            proposal_id=proposal_id,
            reviewer_id=reviewer_id,
            idempotency_key=idempotency_key
        )

    @staticmethod
    @tool
    async def update_ticket(
        ticket_id: str,
        db: AsyncSession,
        status: Optional[str] = None,
        note: Optional[str] = None,
        author: str = "AGENT"
    ) -> Dict[str, Any]:
        try:
            tkt = await ticket_service.update_ticket(
                db=db,
                ticket_id=ticket_id,
                status=status,
                note=note,
                author=author
            )
            return {
                "success": True,
                "ticket_id": tkt.id,
                "status": tkt.status,
                "message": "Ticket successfully updated."
            }
        except Exception as e:
            raise RuntimeError("Ticket update has not been confirmed; retry the ticket step.") from e

write_tools = WriteTools()
