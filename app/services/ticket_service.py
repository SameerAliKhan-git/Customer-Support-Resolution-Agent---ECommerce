"""Ticket lifecycle and customer support ticket service."""
import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Ticket, generate_id
from app.services.audit_service import audit_service

class TicketService:
    @staticmethod
    async def create_ticket(
        db: AsyncSession,
        customer_id: str,
        customer_message: str,
        title: Optional[str] = None,
        order_id: Optional[str] = None,
        category: str = "GENERAL",
        priority: str = "MEDIUM"
    ) -> Ticket:
        now = datetime.datetime.now(datetime.timezone.utc)
        if not title:
            words = customer_message.split()[:8]
            title = " ".join(words) + "..."
            
        ticket = Ticket(
            id=generate_id("tkt"),
            customer_id=customer_id,
            order_id=order_id,
            title=title,
            category=category,
            status="OPEN",
            priority=priority,
            customer_message=customer_message,
            notes=[{
                "author": "CUSTOMER",
                "text": customer_message,
                "timestamp": now.isoformat()
            }],
            created_at=now,
            updated_at=now
        )
        db.add(ticket)
        await db.flush()
        
        await audit_service.log_event(
            db=db,
            entity_type="TICKET",
            entity_id=ticket.id,
            actor_type="CUSTOMER",
            actor_id=customer_id,
            action="TICKET_CREATED",
            details={"order_id": order_id, "category": category}
        )
        await db.commit()
        return ticket

    @staticmethod
    async def update_ticket(
        db: AsyncSession,
        ticket_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        note: Optional[str] = None,
        author: str = "SYSTEM"
    ) -> Ticket:
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        res = await db.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket '{ticket_id}' not found.")
        
        now = datetime.datetime.now(datetime.timezone.utc)
        old_status = ticket.status
        if status:
            ticket.status = status
            if status == "ESCALATED" and not ticket.assigned_to:
                ticket.assigned_to = "queue:support-tier2"
                ticket.due_at = now + datetime.timedelta(hours=24)
        if priority:
            ticket.priority = priority
        if note:
            notes_list = list(ticket.notes)
            notes_list.append({
                "author": author,
                "text": note,
                "timestamp": now.isoformat()
            })
            ticket.notes = notes_list

        ticket.updated_at = now
        await db.flush()

        await audit_service.log_event(
            db=db,
            entity_type="TICKET",
            entity_id=ticket.id,
            actor_type=author,
            actor_id=author,
            action="TICKET_UPDATED",
            details={"old_status": old_status, "new_status": ticket.status, "note_added": bool(note)}
        )
        from app.config import settings
        if settings.INTEGRATION_BASE_URL:
            from app.services.jobs import enqueue
            await enqueue(db, generate_id("sync"), "ticket_sync", {"ticket_id": ticket.id, "status": ticket.status})
        await db.commit()
        return ticket

    @staticmethod
    async def get_ticket(db: AsyncSession, ticket_id: str) -> Optional[Ticket]:
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def list_tickets_for_customer(db: AsyncSession, customer_id: str) -> List[Ticket]:
        stmt = select(Ticket).where(Ticket.customer_id == customer_id).order_by(Ticket.created_at.desc())
        res = await db.execute(stmt)
        return list(res.scalars().all())

ticket_service = TicketService()
