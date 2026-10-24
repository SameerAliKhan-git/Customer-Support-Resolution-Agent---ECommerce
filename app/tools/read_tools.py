"""Typed read tools for investigating customer tickets, orders, returns, and policies."""
from app.services.telemetry import tool
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Order, ReturnRecord, PaymentRecord, RefundOperation, Ticket
from app.services.order_service import order_service
from app.policies.rag_engine import policy_rag_service

class ReadTools:
    """
    Read tools with server-controlled customer scoping.
    """
    @staticmethod
    @tool
    async def get_order(
        order_id: str,
        authenticated_customer_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Fetches order details while validating customer ownership server-side."""
        try:
            order = await order_service.get_order_for_customer(order_id, authenticated_customer_id, db)
            if not order:
                return {
                    "success": False,
                    "error_code": "ORDER_NOT_FOUND",
                    "retryable": False,
                    "message": f"Order '{order_id}' was not found."
                }
            return {
                "success": True,
                "order_id": order.id,
                "customer_id": order.customer_id,
                "currency": order.currency,
                "total_amount_minor": order.total_amount_minor,
                "status": order.status,
                "items": order.items,
                "order_date": order.order_date.isoformat(),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None
            }
        except PermissionError as pe:
            return {
                "success": False,
                "error_code": "UNAUTHORIZED_ORDER_ACCESS",
                "retryable": False,
                "message": str(pe)
            }

    @staticmethod
    @tool
    async def get_return_status(
        order_id: str,
        authenticated_customer_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Fetches return records for an owned order."""
        try:
            # Check ownership first
            order = await order_service.get_order_for_customer(order_id, authenticated_customer_id, db)
            if not order:
                return {"success": False, "error_code": "ORDER_NOT_FOUND", "retryable": False, "message": f"Order '{order_id}' not found."}
            
            returns = await order_service.get_return_records(order_id, db)
            if not returns:
                return {
                    "success": False,
                    "error_code": "NO_RETURN_RECORD",
                    "retryable": False,
                    "message": f"No return request has been initiated for order '{order_id}'."
                }
            r = returns[0]
            return {
                "success": True,
                "return_id": r.id,
                "created_at": r.created_at.isoformat(),
                "order_id": r.order_id,
                "status": r.status,
                "tracking_number": r.tracking_number,
                "carrier": r.carrier,
                "return_reason": r.return_reason,
                "inspection_notes": r.inspection_notes,
                "received_at": r.received_at.isoformat() if r.received_at else None
            }
        except PermissionError as pe:
            return {"success": False, "error_code": "UNAUTHORIZED_ORDER_ACCESS", "retryable": False, "message": str(pe)}

    @staticmethod
    @tool
    async def get_payment_status(
        order_id: str,
        authenticated_customer_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Fetches payment and balance details for an owned order."""
        try:
            order = await order_service.get_order_for_customer(order_id, authenticated_customer_id, db)
            if not order:
                return {"success": False, "error_code": "ORDER_NOT_FOUND", "retryable": False, "message": f"Order '{order_id}' not found."}
            
            payment = await order_service.get_payment_record(order_id, db)
            if not payment:
                return {"success": False, "error_code": "PAYMENT_NOT_FOUND", "retryable": False, "message": f"No payment on file for order '{order_id}'."}
            
            return {
                "success": True,
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "amount_minor": payment.amount_minor,
                "currency": payment.currency,
                "status": payment.status,
                "refunded_amount_minor": payment.refunded_amount_minor,
                "reserved_refund_minor": payment.reserved_refund_minor,
                "refundable_balance_minor": payment.refundable_balance_minor,
                "transaction_reference": payment.transaction_reference
            }
        except PermissionError as pe:
            return {"success": False, "error_code": "UNAUTHORIZED_ORDER_ACCESS", "retryable": False, "message": str(pe)}

    @staticmethod
    @tool
    async def get_refund_status(
        operation_id: str,
        db: AsyncSession,
        authenticated_customer_id: str
    ) -> Dict[str, Any]:
        """Queries the status of a specific refund operation."""
        stmt = select(RefundOperation).where(RefundOperation.id == operation_id)
        res = await db.execute(stmt)
        op = res.scalar_one_or_none()
        if not op:
            return {"success": False, "error_code": "OPERATION_NOT_FOUND", "retryable": False, "message": f"Operation '{operation_id}' not found."}
        if op.customer_id != authenticated_customer_id:
            return {"success": False, "error_code": "UNAUTHORIZED_ORDER_ACCESS", "retryable": False, "message": "Refund operation is not available to this customer."}
        
        return {
            "success": True,
            "operation_id": op.id,
            "idempotency_key": op.idempotency_key,
            "status": op.status,
            "amount_minor": op.amount_minor,
            "currency": op.currency,
            "gateway_reference": op.gateway_reference,
            "error_code": op.error_code,
            "error_message": op.error_message
        }

    @staticmethod
    @tool
    async def search_policy(
        query: str,
        db: AsyncSession,
        policy_id_filter: Optional[str] = None,
        business_date=None
    ) -> Dict[str, Any]:
        """Retrieves matching policy sections with citations."""
        results = await policy_rag_service.search_policies(
            query=query,
            db=db,
            policy_id_filter=policy_id_filter,
            top_k=3,
            business_date=business_date
        )
        return {
            "success": True,
            "query": query,
            "results": results
        }

    @staticmethod
    @tool
    async def get_ticket(
        ticket_id: str,
        authenticated_customer_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        res = await db.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            return {"success": False, "error_code": "TICKET_NOT_FOUND", "retryable": False, "message": f"Ticket '{ticket_id}' not found."}
        
        # Ownership check
        if ticket.customer_id != authenticated_customer_id:
            return {"success": False, "error_code": "UNAUTHORIZED_TICKET_ACCESS", "retryable": False, "message": "Cannot access ticket of another customer."}
        
        return {
            "success": True,
            "ticket_id": ticket.id,
            "customer_id": ticket.customer_id,
            "order_id": ticket.order_id,
            "title": ticket.title,
            "category": ticket.category,
            "status": ticket.status,
            "priority": ticket.priority,
            "customer_message": ticket.customer_message,
            "notes": ticket.notes
        }

read_tools = ReadTools()
