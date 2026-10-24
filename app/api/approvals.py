"""Reviewer approval management and decision endpoints."""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db, require_reviewer, AuthenticatedUser
from app.schemas.approval import ApprovalDecisionRequest, ApprovalResponse
from app.services.approval_service import approval_service
from app.workflows.engine import workflow_engine
from app.db.models import Approval, RefundProposal

router = APIRouter(prefix="/approvals", tags=["Approvals"])

@router.get("/pending", response_model=List[Dict[str, Any]])
async def list_pending_approvals(
    reviewer: AuthenticatedUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns reviewer queue showing customer, order facts, proposed action, amount,
    evidence references, policy citations, and expiration timestamp.
    """
    items = await approval_service.list_pending_approvals(db)
    from app.db.workflow_store import find_run
    for item in items:
        item["run_id"] = await find_run(item["ticket_id"])
    return items

@router.post("/{approval_id}/decision", response_model=Dict[str, Any])
async def submit_approval_decision(
    approval_id: str,
    decision_req: ApprovalDecisionRequest,
    reviewer: AuthenticatedUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Reviewer submits decision (APPROVED or REJECTED) on a pending refund proposal.
    If approved, securely resumes the LangGraph workflow to disburse funds idempotently.
    """
    try:
        from app.config import settings
        if settings.AUTH_MODE == "oidc" and reviewer.role != "admin":
            record = await db.get(Approval, approval_id)
            proposal = await db.get(RefundProposal, record.proposal_id) if record else None
            if proposal and proposal.amount_minor > settings.OIDC_REVIEW_LIMIT_MINOR:
                raise HTTPException(status_code=403, detail="This amount requires a senior reviewer.")
        approval = await approval_service.decide_approval(
            db=db,
            approval_id=approval_id,
            decision=decision_req.decision,
            reviewer_id=reviewer.user_id,
            reviewer_name=reviewer.name,
            decision_notes=decision_req.decision_notes
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    from app.db.workflow_store import find_run
    proposal = await db.get(RefundProposal, approval.proposal_id)
    run_id = await find_run(proposal.ticket_id)
    if not run_id:
        raise HTTPException(status_code=409, detail="Decision saved. No workflow exists for this proposal.")
    from app.config import settings
    if settings.ASYNC_WORKFLOWS:
        from app.services.jobs import enqueue
        await enqueue(db, run_id, revive=True)
        await db.commit()
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"success": True, "approval_id": approval.id,
            "run_id": run_id, "decision": approval.decision, "execution_status": "QUEUED"})
    state = await workflow_engine.resume_workflow(run_id, {})
    return {"success": True, "approval_id": approval.id, "proposal_id": proposal.id,
        "decision": approval.decision, "decided_at": approval.decided_at.isoformat(),
        "workflow_state": state, "workflow_outcome": {
            "success": state.get("execution_status") == "SUCCEEDED",
            "status": state.get("execution_status"), "gateway_reference": state.get("external_result_reference"),
            "amount_minor": proposal.amount_minor, "currency": proposal.currency,
            "message": state.get("final_response")}}
