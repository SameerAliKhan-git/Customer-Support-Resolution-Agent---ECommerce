"""Pydantic schemas for refund proposals."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class RefundProposalCreate(BaseModel):
    action: str = Field(default="request_refund_approval", description="Proposed action type")
    order_id: str = Field(..., description="Target order ID")
    amount_minor: int = Field(..., gt=0, description="Amount in minor currency units (cents)")
    currency: str = Field(default="USD", description="Three-letter currency code")
    reason: str = Field(..., description="Detailed justification grounded in policies and facts")
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of orders, returns, payments")
    policy_refs: List[str] = Field(default_factory=list, description="Policy and section citations")
    missing_information: List[str] = Field(default_factory=list, description="List of unverified or missing details")

class RefundProposalResponse(BaseModel):
    id: str
    ticket_id: str
    order_id: str
    customer_id: str
    amount_minor: int
    currency: str
    reason: str
    evidence_refs: List[str]
    policy_refs: List[str]
    missing_information: List[str]
    status: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
