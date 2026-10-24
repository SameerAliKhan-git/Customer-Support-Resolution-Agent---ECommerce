"""Specialist Classification Agent: categorizes customer complaints and extracts order entities."""
import re
from typing import Dict, Any, Optional

class ClassificationAgent:
    """
    Classifies customer messages into:
    - REFUND_REQUEST
    - ORDER_STATUS
    - DAMAGED_ITEM
    - ESCALATION
    - GENERAL
    """
    @staticmethod
    async def classify(message: str, explicit_order_id: Optional[str] = None) -> Dict[str, Any]:
        msg_lower = message.lower()

        # Extract order ID if embedded in message (e.g., ord_1001, order #1001, ord-1001)
        order_id = explicit_order_id
        if not order_id:
            order_match = re.search(r'\b(ord[_-]?[0-9]{3,6})\b', msg_lower)
            if order_match:
                order_id = order_match.group(1).replace("-", "_")

        # Check for immediate escalation triggers
        if any(term in msg_lower for term in [
            "lawyer", "attorney", "legal action", "lawsuit", "bbb", "ftc",
            "fraud", "chargeback", "dispute", "scam", "police", "stolen"
        ]):
            return {
                "category": "ESCALATION",
                "extracted_order_id": order_id,
                "confidence": 0.98,
                "urgency": "HIGH",
                "reason": "Complaint contains legal, fraud, or chargeback escalation triggers."
            }

        # Check for Damaged Item
        if any(term in msg_lower for term in [
            "damaged", "broken", "smashed", "shattered", "scratched",
            "cracked", "defective", "doa", "dent", "faulty", "ruined", "opened box"
        ]):
            return {
                "category": "DAMAGED_ITEM",
                "extracted_order_id": order_id,
                "confidence": 0.95,
                "urgency": "HIGH",
                "reason": "Customer is reporting physical damage or defect on arrival."
            }

        # Check for Refund Request
        if any(term in msg_lower for term in [
            "refund", "return", "money back", "returned", "sent back",
            "haven't received my refund", "where is my refund", "reimburse"
        ]):
            return {
                "category": "REFUND_REQUEST",
                "extracted_order_id": order_id,
                "confidence": 0.96,
                "urgency": "MEDIUM",
                "reason": "Customer is requesting refund or checking return reimbursement status."
            }

        # Check for Order Status / Tracking
        if any(term in msg_lower for term in [
            "where is my", "where my", "where is", "order status", "tracking", "track", "shipped",
            "delivery date", "when will it arrive", "when will", "package", "transit", "delay", "latest update"
        ]):
            return {
                "category": "ORDER_STATUS",
                "extracted_order_id": order_id,
                "confidence": 0.92,
                "urgency": "LOW",
                "reason": "Customer inquiry regarding package location or estimated delivery."
            }


        return {
            "category": "GENERAL",
            "extracted_order_id": order_id,
            "confidence": 0.80,
            "urgency": "LOW",
            "reason": "General customer inquiry."
        }

classification_agent = ClassificationAgent()
