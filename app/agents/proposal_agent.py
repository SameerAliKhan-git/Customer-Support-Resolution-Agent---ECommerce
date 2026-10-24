"""Specialist Proposal Agent: creates structured resolution proposals adhering to Section 10 schemas."""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

class ProposalAgent:
    """
    Synthesizes facts, policies, and business rules to propose safe resolutions.
    """
    @staticmethod
    def generate_resolution(
        complaint_category: str,
        customer_id: str,
        order_id: Optional[str],
        verified_facts: Dict[str, Any],
        policy_citations: List[str],
        missing_information: List[str]
    ) -> Dict[str, Any]:
        """
        Determines the appropriate business resolution:
        - request_refund_approval
        - answer_only
        - request_clarification
        - escalate_to_human
        """
        # If missing critical information
        if not order_id or (missing_information and "order_id:" in missing_information[0]):
            return {
                "action": "request_clarification",
                "reason": "Missing order reference.",
                "explanation": "To help investigate your inquiry, please provide your order ID (e.g., ord_1001).",
                "proposed_amount_minor": 0,
                "evidence_refs": [],
                "policy_refs": policy_citations,
                "missing_information": missing_information
            }

        order_data = verified_facts.get("order", {})
        if not order_data or not order_data.get("success"):
            return {
                "action": "answer_only",
                "reason": "Invalid or inaccessible order.",
                "explanation": f"We could not locate an active order with ID '{order_id}' under your account.",
                "proposed_amount_minor": 0,
                "evidence_refs": [],
                "policy_refs": policy_citations,
                "missing_information": missing_information
            }

        # Handling Escalations
        if complaint_category == "ESCALATION":
            return {
                "action": "escalate_to_human",
                "reason": "Customer complaint matches policy exception criteria requiring human specialist review.",
                "explanation": "Your inquiry has been placed in the support escalation queue for specialist review.",
                "proposed_amount_minor": 0,
                "evidence_refs": [f"order_{order_id}"],
                "policy_refs": policy_citations,
                "missing_information": []
            }

        # Handling Damaged Items
        if complaint_category == "DAMAGED_ITEM":
            total_minor = order_data.get("total_amount_minor", 0)
            evidence_refs = [f"order_{order_id}"]
            if verified_facts.get("payment", {}).get("payment_id"):
                evidence_refs.append(f"payment_{verified_facts['payment']['payment_id']}")

            if total_minor > 50000: # Over $500 requires Tier 2 human escalation per policy
                return {
                    "action": "escalate_to_human",
                    "reason": f"Damaged goods claim value (${total_minor/100:.2f}) exceeds high-value threshold ($500.00).",
                    "explanation": f"Because your order total is ${total_minor/100:.2f}, your damage report requires specialist review and has been placed in the support escalation queue.",
                    "proposed_amount_minor": 0,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": []
                }
            else:
                delivery = order_data.get("delivery_date")
                age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(delivery).replace(tzinfo=timezone.utc)).days if delivery else None
                inspected = verified_facts.get("return") or {}
                if age_days is None or age_days > 7 or (total_minor > 10000 and inspected.get("status") != "INSPECTION_PASSED"):
                    return {"action": "escalate_to_human", "reason": "Damage claim requires evidence or window review.",
                        "explanation": "A specialist must verify the delivery window and damage evidence before a refund can be proposed.",
                        "proposed_amount_minor": 0, "evidence_refs": evidence_refs, "policy_refs": policy_citations, "missing_information": []}
                return {
                    "action": "request_refund_approval",
                    "order_id": order_id,
                    "amount_minor": total_minor,
                    "currency": order_data.get("currency", "USD"),
                    "reason": "Damage claim within reporting window; inspection evidence verified where required.",
                    "explanation": f"We are so sorry your order arrived damaged. A refund proposal for ${total_minor/100:.2f} has been submitted for supervisor approval.",
                    "proposed_amount_minor": total_minor,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": []
                }

        # Handling Order Status
        if complaint_category == "ORDER_STATUS":
            status = order_data.get("status")
            items = ", ".join([item.get("name", "Item") for item in order_data.get("items", [])])
            evidence_refs = [f"order_{order_id}"]
            
            if status == "DELIVERED":
                del_date = order_data.get("delivery_date", "recently")
                exp = f"Your order ({items}) was delivered on {del_date}. If you cannot find the package, please check with building reception or neighbors."
            elif status == "SHIPPED":
                exp = f"Your order ({items}) has been shipped and is currently in transit. Delivery timing has not been confirmed."
            else:
                exp = f"Your order ({items}) is currently in status: {status}."

            shipment = verified_facts.get("shipment", {})
            if shipment.get("estimated_delivery"):
                exp += f" The carrier estimates delivery at {shipment['estimated_delivery']} (an estimate, not a guarantee)."
            if shipment.get("location"):
                exp += f" Latest carrier location: {shipment['location']}."
            return {
                "action": "answer_only",
                "reason": "Order status inquiry resolved with current shipping records.",
                "explanation": exp,
                "proposed_amount_minor": 0,
                "evidence_refs": evidence_refs,
                "policy_refs": policy_citations,
                "missing_information": []
            }

        # Handling Refund Requests
        if complaint_category == "REFUND_REQUEST":
            ret = verified_facts.get("return")
            pay = verified_facts.get("payment")
            
            evidence_refs = [f"order_{order_id}"]
            if pay and pay.get("payment_id"):
                evidence_refs.append(f"payment_{pay['payment_id']}")
            if ret and ret.get("return_id"):
                evidence_refs.append(f"return_{ret['return_id']}")

            # Check if return exists
            if not ret:
                delivery = order_data.get("delivery_date")
                age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(delivery).replace(tzinfo=timezone.utc)).days if delivery else None
                explanation = "According to our return policy, refunds are issued after a return is initiated and received. We do not show an active return for this order."
                if age_days is not None and age_days > 30:
                    explanation = f"Our return policy allows standard returns within 30 days of delivery. This order was delivered {age_days} days ago and has no active return, so a standard refund cannot be issued. A senior support specialist can review an exception."
                return {
                    "action": "answer_only",
                    "reason": "No return record found.",
                    "explanation": explanation,
                    "proposed_amount_minor": 0,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": ["return_record: Return has not been initiated by customer."]
                }

            delivery = order_data.get("delivery_date")
            created = ret.get("created_at")
            if delivery and created:
                return_age = (datetime.fromisoformat(created) - datetime.fromisoformat(delivery)).days
                if return_age > 30:
                    return {"action": "escalate_to_human", "reason": "Return initiated outside standard window.",
                        "explanation": "This return was initiated after the 30-day return policy window. A senior supervisor must review an exception.",
                        "proposed_amount_minor": 0, "evidence_refs": evidence_refs, "policy_refs": policy_citations, "missing_information": []}

            ret_status = ret.get("status")

            if ret_status == "IN_TRANSIT":
                tracking = ret.get("tracking_number", "in transit")
                return {
                    "action": "answer_only",
                    "reason": "Return package in transit; warehouse has not received it yet.",
                    "explanation": f"Your return package (tracking: {tracking}) is currently in transit to our warehouse. Per our policy, refunds become eligible once the return is received and inspection passes.",
                    "proposed_amount_minor": 0,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": ["warehouse_receipt: Return package not yet delivered to dock."]
                }

            if ret_status == "INSPECTION_FAILED" or ret_status == "REJECTED":
                notes = ret.get("inspection_notes", "Condition did not meet return standards.")
                return {
                    "action": "escalate_to_human",
                    "reason": f"Return inspection failed: {notes}",
                    "explanation": f"Your returned item did not pass quality inspection ({notes}). Under Section 2 of our Refund Policy, standard refund is blocked. This ticket has been escalated for supervisor review.",
                    "proposed_amount_minor": 0,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": []
                }

            if ret_status == "INSPECTION_PASSED":
                refundable = pay.get("refundable_balance_minor", 0) if pay else 0
                if refundable <= 0:
                    return {
                        "action": "answer_only",
                        "reason": "No unreserved refundable balance remains.",
                        "explanation": f"Order {order_id} has no available refund balance. It may already be refunded or have a refund awaiting review.",
                        "proposed_amount_minor": 0,
                        "evidence_refs": evidence_refs,
                        "policy_refs": policy_citations,
                        "missing_information": []
                    }

                # Fully eligible! Request approval
                return {
                    "action": "request_refund_approval",
                    "order_id": order_id,
                    "amount_minor": refundable,
                    "currency": order_data.get("currency", "USD"),
                    "reason": f"Return received and inspection passed ({ret.get('inspection_notes', 'All items verified')}). Eligible for refund.",
                    "explanation": f"Your returned item was received and passed inspection. A refund proposal for ${refundable/100:.2f} has been created and submitted for supervisor approval.",
                    "proposed_amount_minor": refundable,
                    "evidence_refs": evidence_refs,
                    "policy_refs": policy_citations,
                    "missing_information": []
                }

        # Fallback
        return {
            "action": "answer_only",
            "reason": "General customer inquiry processed.",
            "explanation": "Thank you for contacting ElectroVault Support. How else can we assist you today?",
            "proposed_amount_minor": 0,
            "evidence_refs": [f"order_{order_id}"] if order_id else [],
            "policy_refs": policy_citations,
            "missing_information": []
        }

proposal_agent = ProposalAgent()
