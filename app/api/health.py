"""Health check and interactive demo scenario definitions."""
from typing import Dict, Any, List
from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["Health & Demos"])

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "currency": settings.CURRENCY
    }

@router.get("/demo/scenarios")
async def get_demo_scenarios() -> List[Dict[str, Any]]:
    """
    Returns curated scenarios demonstrating the 3 core portfolio stories:
    - Demo A: Successful approved refund (Alice - ord_1001)
    - Demo B: Correctly blocked ineligible request (Bob - ord_1002 / Emma - ord_1005)
    - Demo C: Failure recovery and timeout reconciliation (David - ord_1008)
    - Plus Damaged Item and Shipping Delay inquiries!
    """
    return [
        {
            "id": "scenario_a",
            "title": "Scenario A: Successful Approved Refund",
            "category": "REFUND_REQUEST",
            "customer_id": "cust_1001",
            "customer_name": "Alice Johnson",
            "order_id": "ord_1001",
            "message": "I returned my headphones last week, but I still haven't received my refund.",
            "description": "Return was received at warehouse and passed inspection. Proposal is submitted to human reviewer. Upon approval, mock payment gateway issues refund with zero duplicates.",
            "expected_outcome": "Awaiting Reviewer Approval -> Reviewer Approves -> Gateway Confirmed ($249.99) -> Ticket Resolved"
        },
        {
            "id": "scenario_b",
            "title": "Scenario B: Correctly Blocked Ineligible Refund",
            "category": "REFUND_REQUEST",
            "customer_id": "cust_1002",
            "customer_name": "Bob Smith",
            "order_id": "ord_1002",
            "message": "I would like to return this USB-C dock and get my money back.",
            "description": "Order delivered 45 days ago, exceeding the 30-day return policy window. No return intake exists. System explains policy clearly and moves NO money.",
            "expected_outcome": "Blocked by policy (return_policy_v1:section_1) -> Zero financial actions -> Grounded explanation to customer"
        },
        {
            "id": "scenario_b2",
            "title": "Scenario B2: Return In Transit (Premature Refund Request)",
            "category": "REFUND_REQUEST",
            "customer_id": "cust_1005",
            "customer_name": "Emma Davis",
            "order_id": "ord_1005",
            "message": "I dropped off my security camera at UPS 2 days ago. Please send my refund.",
            "description": "Tracking shows package in transit. Return not yet received or inspected by warehouse dock. System cites Section 2 of Refund Policy and informs customer.",
            "expected_outcome": "Answered with tracking checkpoint -> Informs refund will trigger once inspection passes"
        },
        {
            "id": "scenario_c",
            "title": "Scenario C: Gateway Timeout & Automatic Reconciliation",
            "category": "REFUND_REQUEST",
            "customer_id": "cust_1004",
            "customer_name": "David Miller",
            "order_id": "ord_1008",
            "message": "My studio microphone return was inspected. Can you process the refund now?",
            "description": "Payment gateway experiences simulated network timeout after accepting the transaction. The agent detects the uncertain result, avoids duplicate execution, and safely queries the gateway by idempotency key to reconcile.",
            "expected_outcome": "Timeout handled -> PENDING_RECONCILIATION -> Reconciled via idempotency key -> Succeeded with 0 duplicate charges"
        },
        {
            "id": "scenario_order_status",
            "title": "Scenario D: Order Tracking & Shipping Delay",
            "category": "ORDER_STATUS",
            "customer_id": "cust_1003",
            "customer_name": "Carol White",
            "order_id": "ord_1003",
            "message": "Where is my mechanical gaming keyboard right now?",
            "description": "Queries carrier shipping API, extracts live checkpoint, and provides reassuring grounded answer without unnecessary financial steps.",
            "expected_outcome": "Live tracking facts returned -> Reassuring response -> Ticket updated"
        },
        {
            "id": "scenario_damaged_high_value",
            "title": "Scenario E: High-Value Damaged Goods Escalation",
            "category": "DAMAGED_ITEM",
            "customer_id": "cust_1004",
            "customer_name": "David Miller",
            "order_id": "ord_1004",
            "message": "The 4K Ultra-HD monitor screen is cracked down the middle right out of the box!",
            "description": "Damaged goods report. Checks policy threshold: damage on goods over $500 triggers immediate Tier 2 escalation to human team.",
            "expected_outcome": "Detected >$500 threshold -> Escalated to Priority Care Team -> Ticket marked ESCALATED"
        }
    ]
