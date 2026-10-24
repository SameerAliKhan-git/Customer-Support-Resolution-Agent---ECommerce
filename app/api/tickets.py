"""Ticket management and audit inquiry endpoints."""
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db, get_current_user, require_reviewer, AuthenticatedUser
from app.schemas.ticket import TicketResponse, AuditEventResponse
from app.services.ticket_service import ticket_service
from app.db.models import Ticket, AuditEvent, RefundProposal, Approval, RefundOperation

router = APIRouter(prefix="/tickets", tags=["Tickets"])

class EvidenceInput(BaseModel):
    description: str = Field(min_length=5, max_length=3000)

@router.post("/{ticket_id}/evidence")
async def add_evidence(ticket_id: str, evidence: EvidenceInput, user=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    ticket = await ticket_service.get_ticket(db,ticket_id)
    if not ticket or (not user.is_reviewer and ticket.customer_id != user.user_id):
        raise HTTPException(404,"Ticket not found.")
    if len(ticket.evidence) >= 20:
        raise HTTPException(409,"Evidence limit reached.")
    from datetime import datetime,timezone
    ticket.evidence = [*ticket.evidence,{"description":evidence.description,"submitted_by":user.user_id,"created_at":datetime.now(timezone.utc).isoformat(),"verified":False}]
    await db.commit()
    return {"saved":True,"verified":False}

@router.post("/{ticket_id}/claim")
async def claim_ticket(ticket_id: str, user=Depends(require_reviewer), db: AsyncSession=Depends(get_db)):
    ticket = (await db.execute(select(Ticket).where(Ticket.id==ticket_id).with_for_update())).scalar_one_or_none()
    if not ticket:
        raise HTTPException(404,"Ticket not found.")
    if ticket.assigned_to and not ticket.assigned_to.startswith("queue:") and ticket.assigned_to != user.user_id:
        raise HTTPException(409,"Another reviewer owns this ticket.")
    ticket.assigned_to = user.user_id
    await db.commit()
    return {"ticket_id":ticket.id,"assigned_to":ticket.assigned_to,"due_at":ticket.due_at}

@router.get("", response_model=List[TicketResponse])
async def list_tickets(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists all support tickets for the authenticated customer (or all if reviewer)."""
    if current_user.is_reviewer:
        stmt = select(Ticket).order_by(Ticket.created_at.desc())
        res = await db.execute(stmt)
        return list(res.scalars().all())
    else:
        return await ticket_service.list_tickets_for_customer(db, current_user.user_id)

@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ticket = await ticket_service.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    
    # Ownership verification
    if current_user.is_customer and ticket.customer_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot view tickets for another customer.")
    
    return ticket

@router.get("/{ticket_id}/audit-trail", response_model=List[AuditEventResponse])
async def get_ticket_audit_trail(
    ticket_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns chronological audit trail of all agent, system, and human actions on this ticket."""
    ticket = await ticket_service.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    
    if current_user.is_customer and ticket.customer_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot view audit trails for another customer.")
        
    proposal_ids = select(RefundProposal.id).where(RefundProposal.ticket_id == ticket_id)
    approval_ids = select(Approval.id).where(Approval.proposal_id.in_(proposal_ids))
    operation_ids = select(RefundOperation.id).where(RefundOperation.proposal_id.in_(proposal_ids))
    stmt = (
        select(AuditEvent)
        .where(
            (AuditEvent.entity_id == ticket_id) | 
            AuditEvent.entity_id.in_(proposal_ids) |
            AuditEvent.entity_id.in_(approval_ids) |
            AuditEvent.entity_id.in_(operation_ids)
        )
        .order_by(AuditEvent.created_at.asc())
    )
    res = await db.execute(stmt)
    events = list(res.scalars().all())
    if current_user.is_reviewer:
        return events
    allowed = {"order_id", "amount_minor", "currency", "gateway_reference", "old_status", "new_status", "category", "proposal_id", "approval_id", "policy_refs", "note_added"}
    return [{"id":event.id,"entity_type":event.entity_type,"entity_id":event.entity_id,
        "actor_type":event.actor_type,"actor_id":"support" if event.actor_type != "CUSTOMER" else current_user.user_id,
        "action":event.action,"details":{k:v for k,v in event.details.items() if k in allowed},"created_at":event.created_at} for event in events]
