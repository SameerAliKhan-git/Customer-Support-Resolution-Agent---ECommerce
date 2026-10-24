"""Specialist Policy Retrieval Agent: maps customer context to policy rules with citations."""
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.read_tools import read_tools

class PolicyRetrievalAgent:
    """
    Retrieves grounded policies with exact citations and section identifiers.
    """
    @staticmethod
    async def retrieve_policies(
        complaint_category: str,
        customer_message: str,
        verified_facts: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        # Formulate targeted queries grounded in category and facts
        queries = []
        policy_filter = None

        if complaint_category == "REFUND_REQUEST":
            policy_filter = None
            queries.append("refund eligibility return received inspection passed human approval")
            queries.append("standard return window 30 days return processing policy")

        elif complaint_category == "DAMAGED_ITEM":
            policy_filter = "damaged_goods_policy_v1"
            queries.append("damaged on arrival reporting window replacement refund")
            queries.append("high value damaged goods escalation")
        elif complaint_category == "ORDER_STATUS":
            policy_filter = "shipping_delay_policy_v1"
            queries.append("shipping transit times tracking delay lost in transit")
        elif complaint_category == "ESCALATION":
            policy_filter = "exception_policy_v1"
            queries.append("conditions requiring immediate human escalation legal dispute fraud")
        else:
            queries.append(customer_message)

        citations: List[str] = []
        retrieved_passages: List[Dict[str, Any]] = []

        from datetime import datetime
        order = verified_facts.get("order", {})
        date_value = order.get("delivery_date") or order.get("order_date")
        business_date = datetime.fromisoformat(date_value) if date_value else None
        for q in queries:
            search_res = await read_tools.search_policy(q, db, policy_id_filter=policy_filter, business_date=business_date)
            for item in search_res.get("results", []):
                cit = item.get("citation")
                if cit and cit not in citations:
                    citations.append(cit)
                    retrieved_passages.append(item)

        return {
            "policy_citations": citations,
            "passages": retrieved_passages,
            "applicable_policy_established": len(citations) > 0
        }

policy_retrieval_agent = PolicyRetrievalAgent()
