"""Pydantic schemas for refund operations and executions."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class RefundExecutionRequest(BaseModel):
    proposal_id: str = Field(..., description="Approved refund proposal ID")
    reviewer_id: str = Field(..., description="Reviewer authorization identity")
    idempotency_key: Optional[str] = Field(None, description="Optional custom client idempotency key")

class RefundOperationResponse(BaseModel):
    id: str
    idempotency_key: str
    proposal_id: str
    order_id: str
    customer_id: str
    amount_minor: int
    currency: str
    status: str
    gateway_reference: Optional[str]
    attempt_count: int
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
