"""Pydantic schemas for orders, returns, and payments."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class OrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    price_minor: int

class OrderResponse(BaseModel):
    id: str
    customer_id: str
    currency: str
    total_amount_minor: int
    status: str
    items: List[Dict[str, Any]]
    order_date: datetime
    delivery_date: Optional[datetime]

    class Config:
        from_attributes = True

class ReturnResponse(BaseModel):
    id: str
    order_id: str
    customer_id: str
    status: str
    tracking_number: Optional[str]
    carrier: Optional[str]
    return_reason: Optional[str]
    inspection_notes: Optional[str]
    received_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class PaymentResponse(BaseModel):
    id: str
    order_id: str
    customer_id: str
    amount_minor: int
    currency: str
    payment_method: str
    status: str
    refunded_amount_minor: int
    reserved_refund_minor: int
    refundable_balance_minor: int
    transaction_reference: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
