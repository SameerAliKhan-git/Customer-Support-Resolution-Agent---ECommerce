"""Order, return, and payment data access service with ownership checking."""
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Order, ReturnRecord, PaymentRecord
from mock_services.shipping.mock_shipping_api import mock_shipping_service

class OrderService:
    @staticmethod
    async def get_order_for_customer(
        order_id: str,
        customer_id: str,
        db: AsyncSession
    ) -> Optional[Order]:
        stmt = select(Order).where(Order.id == order_id)
        res = await db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            return None
        # Strict ownership validation
        if order.customer_id != customer_id:
            raise PermissionError(f"Customer '{customer_id}' does not have access to order '{order_id}'.")
        return order

    @staticmethod
    async def get_return_records(order_id: str, db: AsyncSession) -> List[ReturnRecord]:
        stmt = select(ReturnRecord).where(ReturnRecord.order_id == order_id)
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_payment_record(order_id: str, db: AsyncSession) -> Optional[PaymentRecord]:
        stmt = select(PaymentRecord).where(PaymentRecord.order_id == order_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_full_order_facts(
        order_id: str,
        customer_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Retrieves verified facts across orders, returns, tracking, and payments.
        """
        order = await OrderService.get_order_for_customer(order_id, customer_id, db)
        if not order:
            return {"found": False, "error": f"Order {order_id} not found."}

        returns = await OrderService.get_return_records(order_id, db)
        payment = await OrderService.get_payment_record(order_id, db)

        # Query carrier tracking if tracking number exists
        carrier_info = None
        if returns and returns[0].tracking_number:
            carrier_info = await mock_shipping_service.get_tracking_info(returns[0].tracking_number)

        return {
            "found": True,
            "order": {
                "id": order.id,
                "customer_id": order.customer_id,
                "currency": order.currency,
                "total_amount_minor": order.total_amount_minor,
                "status": order.status,
                "items": order.items,
                "order_date": order.order_date.isoformat(),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
            },
            "returns": [
                {
                    "id": r.id,
                    "status": r.status,
                    "tracking_number": r.tracking_number,
                    "carrier": r.carrier,
                    "return_reason": r.return_reason,
                    "inspection_notes": r.inspection_notes,
                    "received_at": r.received_at.isoformat() if r.received_at else None,
                }
                for r in returns
            ],
            "payment": {
                "id": payment.id,
                "amount_minor": payment.amount_minor,
                "currency": payment.currency,
                "status": payment.status,
                "refunded_amount_minor": payment.refunded_amount_minor,
                "reserved_refund_minor": payment.reserved_refund_minor,
                "refundable_balance_minor": payment.refundable_balance_minor,
                "transaction_reference": payment.transaction_reference,
            } if payment else None,
            "carrier_tracking": carrier_info.get("data") if carrier_info else None
        }

order_service = OrderService()
