"""LangGraph workflow state schema matching Section 10 structured state specification."""
from typing import TypedDict, Optional, List, Dict, Any

class ResolutionState(TypedDict, total=False):
    # Core identifiers & inputs
    run_id: str
    ticket_id: str
    authenticated_customer_id: str
    order_id: Optional[str]
    complaint_category: str
    customer_message: str

    # Grounded evidence & citations
    verified_facts: Dict[str, Any]
    policy_references: List[str]
    missing_information: List[str]

    # Proposal & Approval lifecycle
    action_type: str # request_refund_approval, answer_only, request_clarification, escalate_to_human
    proposed_action_id: Optional[str]
    approval_id: Optional[str]
    proposal_summary: Dict[str, Any]
    reviewer_decision: Optional[Dict[str, Any]] # {"decision": "APPROVED", "reviewer_id": "rev_1"}

    # Execution & Verification
    execution_status: str # NOT_STARTED, PENDING_APPROVAL, EXECUTED, FAILED, TIMED_OUT, RECONCILED
    external_result_reference: Optional[str]
    retry_counts: int
    error_details: Optional[str]

    # Final outcome
    final_response: Optional[str]
    is_paused: bool
    is_completed: bool
