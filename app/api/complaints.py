"""Customer complaint submission endpoint."""
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, AuthenticatedUser, verify_order_ownership
from app.schemas.ticket import ComplaintSubmission
from app.schemas.workflow import WorkflowRunResponse
from app.workflows.engine import workflow_engine

router = APIRouter(prefix="/complaints", tags=["Complaints"])

@router.post("", response_model=WorkflowRunResponse, status_code=status.HTTP_200_OK)
async def submit_complaint(
    complaint: ComplaintSubmission,
    idempotency_key: str | None = Header(default=None, max_length=128),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit customer complaint. Derives customer identity strictly from authenticated user.
    """
    # Customer scope enforcement
    customer_id = current_user.user_id if current_user.is_customer else complaint.customer_id
    if not customer_id:
        raise HTTPException(status_code=422, detail="A reviewer must select a customer account.")
    
    # If order_id provided, verify ownership server-side!
    if complaint.order_id:
        await verify_order_ownership(complaint.order_id, customer_id, db)

    from app.config import settings
    if settings.ASYNC_WORKFLOWS:
        from app.services.jobs import submit
        from fastapi.responses import JSONResponse
        try:
            state = await submit(customer_id, complaint.message, complaint.order_id, idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return JSONResponse(status_code=202, content=state, headers={"Location": f"/api/workflows/{state['run_id']}"})

    final_state = await workflow_engine.start_workflow(
        customer_id=customer_id,
        message=complaint.message,
        order_id=complaint.order_id
    )

    return WorkflowRunResponse(
        run_id=final_state["run_id"],
        ticket_id=final_state["ticket_id"],
        authenticated_customer_id=final_state["authenticated_customer_id"],
        order_id=final_state.get("order_id"),
        complaint_category=final_state.get("complaint_category", "GENERAL"),
        customer_message=final_state["customer_message"],
        verified_facts=final_state.get("verified_facts", {}),
        policy_references=final_state.get("policy_references", []),
        missing_information=final_state.get("missing_information", []),
        proposed_action_id=final_state.get("proposed_action_id"),
        approval_id=final_state.get("approval_id"),
        execution_status=final_state.get("execution_status", "NOT_STARTED"),
        external_result_reference=final_state.get("external_result_reference"),
        retry_counts=final_state.get("retry_counts", 0),
        error_details=final_state.get("error_details"),
        final_response=final_state.get("final_response"),
        requires_approval=final_state.get("action_type") == "request_refund_approval",
        action_type=final_state.get("action_type", ""),
        proposal_summary=final_state.get("proposal_summary", {}),
        telemetry=final_state.get("telemetry", {}),
        is_paused=final_state.get("is_paused", False),
        is_completed=final_state.get("is_completed", False)
    )
