"""Specialist Investigation Agent: gathers verifiable facts across customer records and external services."""
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.read_tools import read_tools

class InvestigationAgent:
    """
    Investigates customer claims against system of record and mock external APIs.
    """
    @staticmethod
    async def investigate(
        customer_id: str,
        order_id: Optional[str],
        complaint_category: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        verified_facts: Dict[str, Any] = {}
        missing_information: List[str] = []

        if not order_id:
            missing_information.append("order_id: Customer did not provide a specific order number.")
            return {
                "success": False,
                "verified_facts": verified_facts,
                "missing_information": missing_information,
                "summary": "Missing order ID. Request customer to provide order number."
            }

        # 1. Fetch Order
        order_res = await read_tools.get_order(order_id, customer_id, db)
        if not order_res.get("success"):
            return {
                "success": False,
                "verified_facts": {},
                "missing_information": [f"valid_order: {order_res.get('message')}"],
                "error_code": order_res.get("error_code"),
                "summary": order_res.get("message")
            }
        
        verified_facts["order"] = order_res
        if complaint_category == "ORDER_STATUS":
            from app.services.order_service import order_service
            from app.integrations.ecommerce import shipment
            order = await order_service.get_order_for_customer(order_id, customer_id, db)
            verified_facts["shipment"] = await shipment(order)

        # 2. Fetch Payment
        payment_res = await read_tools.get_payment_status(order_id, customer_id, db)
        if payment_res.get("success"):
            verified_facts["payment"] = payment_res
        else:
            missing_information.append(f"payment_record: {payment_res.get('message')}")

        # 3. For refunds or returns, inspect Return Record
        if complaint_category in ("REFUND_REQUEST", "DAMAGED_ITEM"):
            return_res = await read_tools.get_return_status(order_id, customer_id, db)
            if return_res.get("success"):
                verified_facts["return"] = return_res
            else:
                verified_facts["return"] = None
                missing_information.append("return_record: No return intake or return tracking found.")

        return {
            "success": True,
            "verified_facts": verified_facts,
            "missing_information": missing_information,
            "summary": f"Investigation complete for order {order_id}."
        }

investigation_agent = InvestigationAgent()
