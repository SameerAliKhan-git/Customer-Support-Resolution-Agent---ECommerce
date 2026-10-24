"""Audit trail service for recording all business and agent actions."""
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import AuditEvent, generate_id

class AuditService:
    @staticmethod
    async def log_event(
        db: AsyncSession,
        entity_type: str,
        entity_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        event = AuditEvent(
            id=generate_id("aud"),
            entity_type=entity_type,
            entity_id=entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            details=details or {},
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )
        db.add(event)
        await db.flush()
        return event

audit_service = AuditService()
