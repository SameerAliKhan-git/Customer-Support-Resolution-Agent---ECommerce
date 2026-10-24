"""Pydantic schemas for approvals."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$", description="Reviewer decision")

    reviewer_id: Optional[str] = Field(None, description="Compatibility field; server derives identity from authentication")
    reviewer_name: Optional[str] = Field(None, description="Compatibility field; server derives name from authentication")
    decision_notes: Optional[str] = Field(None, description="Reviewer notes or reason for rejection")

class ApprovalResponse(BaseModel):
    id: str
    proposal_id: str
    reviewer_id: Optional[str]
    reviewer_name: Optional[str]
    decision: str
    decision_notes: Optional[str]
    decided_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
