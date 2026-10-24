"""Pydantic schemas for tickets, customer complaints, and audit events."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ComplaintSubmission(BaseModel):
    customer_id: Optional[str] = Field(None, description="Reviewer-only customer selector; customer identity comes from authentication")
    order_id: Optional[str] = Field(None, description="Optional associated order ID")
    message: str = Field(..., min_length=5, max_length=10000, description="Customer complaint or question")

class TicketCreate(BaseModel):
    customer_id: str
    order_id: Optional[str] = None
    title: str
    category: str = "GENERAL"
    customer_message: str
    priority: str = "MEDIUM"

class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    note: Optional[str] = None
    author: Optional[str] = "SYSTEM"

class TicketResponse(BaseModel):
    id: str
    customer_id: str
    order_id: Optional[str]
    title: str
    category: str
    status: str
    priority: str
    assigned_to: Optional[str] = None
    due_at: Optional[datetime] = None
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    customer_message: str
    notes: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AuditEventResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    actor_type: str
    actor_id: str
    action: str
    details: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
