"""Workflow execution engine managing run lifecycle, checkpointer state, and resume commands."""
import uuid
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.workflows.graph import build_resolution_workflow
from app.workflows.checkpoints import checkpoint_store
from langgraph.types import Command
from app.workflows.state import ResolutionState
from app.services.ticket_service import ticket_service
from app.db.session import AsyncSessionLocal
from app.db.workflow_store import save_state, load_state
from app.db.models import Approval
from sqlalchemy import select
from app.services.telemetry import measure

class WorkflowEngine:
    @staticmethod
    async def start_workflow(
        customer_id: str,
        message: str,
        order_id: Optional[str] = None,
        ticket_id: Optional[str] = None,
        run_id: Optional[str] = None,
        restart_for_clarification: bool = False
    ) -> Dict[str, Any]:
        """
        Initializes and starts a new resolution workflow run.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

        # Ensure ticket exists
        if not ticket_id:
            async with AsyncSessionLocal() as db:
                ticket = await ticket_service.create_ticket(
                    db=db,
                    customer_id=customer_id,
                    order_id=order_id,
                    customer_message=message
                )
                ticket_id = ticket.id

        initial_state: ResolutionState = {
            "run_id": run_id,
            "ticket_id": ticket_id,
            "authenticated_customer_id": customer_id,
            "order_id": order_id,
            "customer_message": message,
            "complaint_category": "GENERAL",
            "verified_facts": {},
            "policy_references": [],
            "missing_information": [],
            "action_type": "",
            "proposed_action_id": None,
            "approval_id": None,
            "reviewer_decision": None,
            "execution_status": "NOT_STARTED",
            "external_result_reference": None,
            "retry_counts": 0,
            "error_details": None,
            "final_response": None,
            "is_paused": False,
            "is_completed": False
        }

        config = {"configurable": {"thread_id": run_id}}
        
        # Execute until end or pause
        async with checkpoint_store() as saver:
            graph = build_resolution_workflow(saver)
            snapshot = await graph.aget_state(config)
            if snapshot.values and not restart_for_clarification:
                # A retried durable job resumes its checkpoint, never restarts side effects.
                if not snapshot.next:
                    await save_state(dict(snapshot.values))
                    return dict(snapshot.values)
                with measure(snapshot.values.get("telemetry")) as measurements:
                    final_state = await graph.ainvoke(None, config=config)
            else:
                await save_state(initial_state)
                with measure() as measurements:
                    final_state = await graph.ainvoke(initial_state, config=config)
        final_state["telemetry"] = measurements
        final_state.pop("__interrupt__", None)
        await save_state(final_state)
        return final_state

    @staticmethod
    async def resume_workflow(
        run_id: str,
        reviewer_decision: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resumes a paused workflow run with reviewer authorization decision.
        """
        config = {"configurable": {"thread_id": run_id}}
        
        # Fetch existing state snapshot
        saved = await WorkflowEngine.get_workflow_state(run_id)
        if not saved:
            raise ValueError(f"No checkpoint found for workflow run '{run_id}'.")

        # Update state with reviewer decision
        current_values = dict(saved)
        if current_values.get("is_completed"):
            return current_values
        async with AsyncSessionLocal() as db:
            approval = (await db.execute(select(Approval).where(Approval.proposal_id == saved.get("proposed_action_id")))).scalar_one_or_none()
            if not approval or approval.decision not in ("APPROVED", "REJECTED", "EXPIRED"):
                raise ValueError("A recorded reviewer decision is required before resuming.")
            current_values["reviewer_decision"] = {
                "decision": approval.decision, "reviewer_id": approval.reviewer_id,
                "reviewer_name": approval.reviewer_name, "decision_notes": approval.decision_notes,
            }
        current_values["is_paused"] = False

        async with checkpoint_store() as saver:
            graph = build_resolution_workflow(saver)
            snapshot = await graph.aget_state(config)
            if not snapshot.values:
                raise ValueError("Durable graph checkpoint is missing; cannot safely replay this workflow.")
            if not snapshot.next and saved.get("execution_status") in ("PROCESSING", "PENDING_RECONCILIATION", "UNKNOWN"):
                await graph.aupdate_state(config, {"reviewer_decision": current_values["reviewer_decision"], "is_completed": False}, as_node="await_approval")
            command = Command(resume=current_values["reviewer_decision"]) if "await_approval" in snapshot.next else None
            with measure(saved.get("telemetry")) as measurements:
                resumed_state = await graph.ainvoke(command, config=config)
        resumed_state["telemetry"] = measurements
        resumed_state.pop("__interrupt__", None)
        await save_state(resumed_state)
        return resumed_state

    @staticmethod
    async def get_workflow_state(run_id: str) -> Optional[Dict[str, Any]]:
        saved = await load_state(run_id)
        if not saved:
            return None
        async with checkpoint_store() as saver:
            graph = build_resolution_workflow(saver)
            snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
            return {**saved, **dict(snapshot.values)} if snapshot.values else saved

workflow_engine = WorkflowEngine()
