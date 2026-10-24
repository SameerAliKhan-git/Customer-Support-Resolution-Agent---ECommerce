"""Pydantic schemas for LangGraph workflow runs and state serialization."""
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class WorkflowRunCreate(BaseModel):
    customer_id: str = Field(..., description="Authenticated customer ID")
    order_id: Optional[str] = Field(None, description="Optional target order ID")
    message: str = Field(..., description="Customer message or issue description")

class WorkflowRunResponse(BaseModel):
    run_id: str
    ticket_id: str
    authenticated_customer_id: str
    order_id: Optional[str]
    complaint_category: str
    customer_message: str
    verified_facts: Dict[str, Any]
    policy_references: List[str]
    missing_information: List[str]
    proposed_action_id: Optional[str]
    approval_id: Optional[str]
    execution_status: str
    external_result_reference: Optional[str]
    retry_counts: int
    error_details: Optional[str]
    final_response: Optional[str]
    requires_approval: bool = False
    action_type: str = ""
    proposal_summary: Dict[str, Any] = Field(default_factory=dict)
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    is_paused: bool = False
    is_completed: bool = False
