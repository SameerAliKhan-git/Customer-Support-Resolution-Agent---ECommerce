"""Workflow status inspection and resumption endpoints."""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_reviewer, AuthenticatedUser, get_db, verify_order_ownership
from sqlalchemy.ext.asyncio import AsyncSession
from app.workflows.engine import workflow_engine

router = APIRouter(prefix="/workflows", tags=["Workflows"])

@router.get("")
async def list_runs(limit: int = 50, offset: int = 0,
    current_user: AuthenticatedUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.db.workflow_store import WorkflowRun
    from app.db.models import Ticket
    query = select(WorkflowRun).join(Ticket, WorkflowRun.ticket_id == Ticket.id)
    if not current_user.is_reviewer:
        query = query.where(Ticket.customer_id == current_user.user_id)
    rows = (await db.execute(query.order_by(Ticket.created_at.desc()).limit(max(1,min(limit,100))).offset(max(0,offset)))).scalars().all()
    return [{"run_id":r.id,"ticket_id":r.ticket_id,"execution_status":r.state.get("execution_status")} for r in rows]

@router.get("/{run_id}/events")
async def run_events(run_id: str, current_user: AuthenticatedUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    state = await workflow_engine.get_workflow_state(run_id)
    if not state or (not current_user.is_reviewer and state["authenticated_customer_id"] != current_user.user_id):
        raise HTTPException(404,"Workflow not found.")
    from app.api.tickets import get_ticket_audit_trail
    return await get_ticket_audit_trail(state["ticket_id"], current_user, db)

class ResumeWorkflowRequest(BaseModel):
    decision: str # "APPROVED" or "REJECTED"
    reviewer_id: str
    reviewer_name: str
    decision_notes: str = ""

class AdditionalMessage(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    order_id: str | None = None

@router.post("/{run_id}/messages")
async def supply_information(run_id: str, req: AdditionalMessage,
    current_user: AuthenticatedUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    state = await workflow_engine.get_workflow_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    if not current_user.is_reviewer and state["authenticated_customer_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Workflow belongs to another customer.")
    if state.get("action_type") != "request_clarification" or state.get("proposed_action_id"):
        raise HTTPException(status_code=409, detail="Only a workflow awaiting clarification accepts additional information.")
    if req.order_id:
        await verify_order_ownership(req.order_id, state["authenticated_customer_id"], db)
    return await workflow_engine.start_workflow(customer_id=state["authenticated_customer_id"],
        message=state["customer_message"] + "\nAdditional information: " + req.message,
        order_id=req.order_id or state.get("order_id"), ticket_id=state["ticket_id"], run_id=run_id,
        restart_for_clarification=True)

@router.get("/{run_id}")
async def get_workflow_run_status(
    run_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    state = await workflow_engine.get_workflow_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found.")
    if not current_user.is_reviewer and state["authenticated_customer_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden: workflow belongs to another customer.")
    return state

@router.post("/{run_id}/resume")
async def resume_workflow_run(
    run_id: str,
    req: ResumeWorkflowRequest,
    current_user: AuthenticatedUser = Depends(require_reviewer)
):
    try:
        resumed = await workflow_engine.resume_workflow(
            run_id=run_id,
            reviewer_decision={
                "decision": req.decision,
                "reviewer_id": req.reviewer_id,
                "reviewer_name": req.reviewer_name,
                "decision_notes": req.decision_notes
            }
        )
        return resumed
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
