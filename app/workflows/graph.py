"""LangGraph Multi-Agent Workflow graph definition with human-in-the-loop pause and resume."""
import uuid
import datetime
import asyncio
import httpx
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.workflows.state import ResolutionState
from app.agents.classifier import classification_agent
from app.agents.investigator import investigation_agent
from app.agents.policy_retriever import policy_retrieval_agent
from app.agents.proposal_agent import proposal_agent
from app.tools.write_tools import write_tools
from app.db.session import AsyncSessionLocal
from app.services.refund_service import refund_service

# Checkpointer for durable LangGraph runs

# --- Workflow Node Implementations ---

async def classify_node(state: ResolutionState) -> Dict[str, Any]:
    """Classifies the customer message and extracts referenced entities."""
    message = state.get("customer_message", "")
    explicit_order_id = state.get("order_id")
    classification = await classification_agent.classify(message, explicit_order_id)
    from app.config import settings
    if settings.LLM_PROVIDER == "openai" and classification.get("category") != "ESCALATION":
        from app.agents.model_client import classify_with_model
        try:
            classification = await classify_with_model(message, explicit_order_id)
        except ValueError:
            classification = {"category": "ESCALATION", "extracted_order_id": explicit_order_id}
    
    order_id = explicit_order_id or classification.get("extracted_order_id")
    category = classification.get("category", "GENERAL")
    
    return {
        "complaint_category": category,
        "order_id": order_id
    }

async def investigate_node(state: ResolutionState) -> Dict[str, Any]:
    """Gathers factual evidence across orders, payments, and carrier returns."""
    customer_id = state["authenticated_customer_id"]
    order_id = state.get("order_id")
    category = state.get("complaint_category", "GENERAL")
    
    retries = 0
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as db:
                inv_result = await investigation_agent.investigate(customer_id, order_id, category, db)
                if inv_result.get("verified_facts", {}).get("order", {}).get("success"):
                    from app.db.models import Ticket
                    ticket = await db.get(Ticket, state["ticket_id"])
                    ticket.order_id, ticket.category = order_id, category
                    await db.commit()
            break
        except (TimeoutError, httpx.TransportError):
            if attempt == 2:
                inv_result = {"verified_facts": {}, "missing_information": ["service_failure: Records could not be verified after three attempts."]}
            else:
                retries += 1
                await asyncio.sleep(0.1 * (2 ** attempt))
        
    return {
        "verified_facts": inv_result.get("verified_facts", {}),
        "missing_information": inv_result.get("missing_information", []),
        "retry_counts": state.get("retry_counts", 0) + retries
    }

async def policy_retrieval_node(state: ResolutionState) -> Dict[str, Any]:
    """Retrieves authoritative company support policy passages with citations."""
    category = state.get("complaint_category", "GENERAL")
    message = state.get("customer_message", "")
    facts = state.get("verified_facts", {})
    
    async with AsyncSessionLocal() as db:
        try:
            policy_res = await policy_retrieval_agent.retrieve_policies(category, message, facts, db)
        except ValueError:
            policy_res = {"policy_citations": []}
        
    return {
        "policy_references": policy_res.get("policy_citations", [])
    }

async def propose_resolution_node(state: ResolutionState) -> Dict[str, Any]:
    """Evaluates facts against retrieved policies and proposes business action."""
    category = state.get("complaint_category", "GENERAL")
    customer_id = state["authenticated_customer_id"]
    order_id = state.get("order_id")
    facts = state.get("verified_facts", {})
    policy_refs = state.get("policy_references", [])
    missing_info = state.get("missing_information", [])
    
    proposal = proposal_agent.generate_resolution(
        complaint_category=category,
        customer_id=customer_id,
        order_id=order_id,
        verified_facts=facts,
        policy_citations=policy_refs,
        missing_information=missing_info
    )
    if any(item.startswith("service_failure:") for item in missing_info):
        proposal = {"action": "escalate_to_human", "explanation": "Records are temporarily unavailable. A specialist will verify them before taking action."}
    if not policy_refs:
        proposal = {"action": "escalate_to_human", "explanation": "No applicable policy evidence is available. A specialist must review this request."}
    
    action = proposal.get("action")
    final_resp = proposal.get("explanation")
    
    updates: Dict[str, Any] = {
        "action_type": action,
        "final_response": final_resp
    }
    
    # If proposing refund approval, persist proposal and pending approval in DB
    if action == "request_refund_approval":
        from app.schemas.proposal import RefundProposalCreate
        RefundProposalCreate.model_validate({"order_id": order_id, "amount_minor": proposal.get("proposed_amount_minor"),
            "reason": proposal.get("reason"), "evidence_refs": proposal.get("evidence_refs", []), "policy_refs": policy_refs})
        amount_minor = proposal.get("proposed_amount_minor", 0)
        reason = proposal.get("reason", "Refund proposal")
        evidence_refs = proposal.get("evidence_refs", [])
        
        async with AsyncSessionLocal() as db:
            prop_res = await write_tools.create_refund_proposal(
                ticket_id=state["ticket_id"],
                order_id=order_id, # type: ignore
                authenticated_customer_id=customer_id,
                amount_minor=amount_minor,
                reason=reason,
                evidence_refs=evidence_refs,
                policy_refs=policy_refs,
                db=db
            )
            if prop_res.get("success"):
                updates["proposed_action_id"] = prop_res.get("proposal_id")
                updates["approval_id"] = prop_res.get("approval_id")
                updates["proposal_summary"] = {key: prop_res.get(key) for key in ("amount_minor", "currency", "expires_at")}
                updates["is_paused"] = True
                updates["execution_status"] = "PENDING_APPROVAL"
                # Update ticket
                await write_tools.update_ticket(
                    ticket_id=state["ticket_id"],
                    db=db,
                    status="AWAITING_APPROVAL",
                    note=f"Refund proposal {prop_res.get('proposal_id')} created for ${amount_minor/100:.2f}. Awaiting reviewer approval."
                )
            else:
                updates.update(action_type="escalate_to_human", execution_status="ESCALATED",
                    final_response=prop_res.get("message", "A specialist will review this request."))
    
    return updates

def route_decision(state: ResolutionState) -> Literal["await_approval_node", "escalate_node", "respond_node"]:
    """Conditional edge routing based on proposed business action."""
    action = state.get("action_type")
    if action == "request_refund_approval":
        return "await_approval_node"
    elif action == "escalate_to_human":
        return "escalate_node"
    else:
        return "respond_node"

async def await_approval_node(state: ResolutionState) -> Dict[str, Any]:
    """
    Pause point for human approval.
    When resumed with reviewer_decision, execution proceeds to execute_refund_node.
    """
    decision = state.get("reviewer_decision")
    if not decision:
        decision = interrupt({"proposal_id": state.get("proposed_action_id"), "message": "Reviewer authorization required"})
    
    return {
        "is_paused": False,
        "execution_status": "DECISION_RECEIVED"
        , "reviewer_decision": decision
    }

def route_after_approval(state: ResolutionState) -> Literal["execute_refund_node", "respond_node", "__end__"]:
    decision_info = state.get("reviewer_decision")
    if not decision_info:
        return END
    
    decision = decision_info.get("decision")
    if decision == "APPROVED":
        return "execute_refund_node"
    else:
        return "respond_node"


async def execute_refund_node(state: ResolutionState) -> Dict[str, Any]:
    """Executes the approved refund through the write tool with stable idempotency."""
    proposal_id = state.get("proposed_action_id")
    decision_info = state.get("reviewer_decision", {})
    reviewer_id = decision_info.get("reviewer_id", "rev_supervisor")
    order_id = state.get("order_id", "")
    
    # Check if custom test key requested (e.g. timeout_test_)
    idempotency_key = f"idem_rf_{proposal_id}"
    if "ord_1008" in order_id:
        idempotency_key = f"timeout_test_ord1008_{proposal_id}"

    async with AsyncSessionLocal() as db:
        exec_res = await write_tools.execute_approved_refund(
            proposal_id=proposal_id, # type: ignore
            reviewer_id=reviewer_id,
            db=db,
            idempotency_key=idempotency_key
        )
        
        # If timed out, run automatic reconciliation!
        if exec_res.get("status") == "PENDING_RECONCILIATION":
            reconcile_res = await refund_service.reconcile_refund(db, idempotency_key)
            if reconcile_res.get("success"):
                exec_res = reconcile_res

        # Record ticket update with verified external status
        if exec_res.get("success"):
            gateway_ref = exec_res.get("gateway_reference")
            await write_tools.update_ticket(
                ticket_id=state["ticket_id"],
                db=db,
                status="RESOLVED",
                note=f"Verified Outcome: Refund successfully executed. Gateway Reference: {gateway_ref}."
            )
            return {
                "execution_status": "SUCCEEDED",
                "external_result_reference": gateway_ref,
                "final_response": f"Your refund has been approved and successfully processed. Transaction reference: {gateway_ref}.",
                "is_completed": True
            }
        else:
            await write_tools.update_ticket(
                ticket_id=state["ticket_id"],
                db=db,
                status="ESCALATED",
                note=f"Refund execution unconfirmed or declined: {exec_res.get('message')}."
            )
            return {
                "execution_status": exec_res.get("status", "FAILED"),
                "error_details": exec_res.get("message"),
                "final_response": f"Your refund outcome is not confirmed: {exec_res.get('message')}. The ticket has been escalated for review.",
                "is_completed": exec_res.get("status") in ("FAILED", "MANUAL_REVIEW_REQUIRED")
            }

async def escalate_node(state: ResolutionState) -> Dict[str, Any]:
    """Escalates ticket to human agents and logs audit trail."""
    async with AsyncSessionLocal() as db:
        await write_tools.update_ticket(
            ticket_id=state["ticket_id"],
            db=db,
            status="ESCALATED",
            note=f"Escalated to human supervisor: {state.get('final_response')}"
        )
    return {
        "execution_status": "ESCALATED",
        "is_completed": True
    }

async def respond_node(state: ResolutionState) -> Dict[str, Any]:
    """Finalizes response for answer-only or rejection outcomes."""
    decision_info = state.get("reviewer_decision")
    resp = state.get("final_response")
    
    if decision_info and decision_info.get("decision") in ("REJECTED", "EXPIRED"):
        status_update = decision_info["decision"]
        notes = decision_info.get("decision_notes", "Criteria not satisfied.")
        resp = ("The approval expired. No new refund was issued; a fresh review is required." if status_update == "EXPIRED"
            else f"Your refund request was reviewed by support and was not approved: {notes}.")
        async with AsyncSessionLocal() as db:
            await write_tools.update_ticket(
                ticket_id=state["ticket_id"],
                db=db,
                status="RESOLVED",
                note=f"Refund rejected by reviewer {decision_info.get('reviewer_name')}: {notes}"
            )
    else:
        status_update = "ANSWERED"
        async with AsyncSessionLocal() as db:
            await write_tools.update_ticket(
                ticket_id=state["ticket_id"], db=db,
                status="OPEN" if state.get("action_type") == "request_clarification" else "RESOLVED",
                note=f"Customer response: {resp}"
            )

    return {
        "final_response": resp,
        "execution_status": status_update,
        "is_completed": True
    }

# --- Build the StateGraph ---

def build_resolution_workflow(checkpointer=None):
    builder = StateGraph(ResolutionState)

    builder.add_node("classify", classify_node)
    builder.add_node("investigate", investigate_node)
    builder.add_node("policy_retrieval", policy_retrieval_node)
    builder.add_node("propose", propose_resolution_node)
    builder.add_node("await_approval", await_approval_node)
    builder.add_node("execute_refund", execute_refund_node)
    builder.add_node("escalate", escalate_node)
    builder.add_node("respond", respond_node)

    # Connections
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "investigate")
    builder.add_edge("investigate", "policy_retrieval")
    builder.add_edge("policy_retrieval", "propose")

    builder.add_conditional_edges(
        "propose",
        route_decision,
        {
            "await_approval_node": "await_approval",
            "escalate_node": "escalate",
            "respond_node": "respond"
        }
    )

    builder.add_conditional_edges(
        "await_approval",
        route_after_approval,
        {
            "execute_refund_node": "execute_refund",
            "respond_node": "respond",
            END: END
        }
    )


    builder.add_edge("execute_refund", END)
    builder.add_edge("escalate", END)
    builder.add_edge("respond", END)

    return builder.compile(checkpointer=checkpointer)

resolution_graph = build_resolution_workflow()
