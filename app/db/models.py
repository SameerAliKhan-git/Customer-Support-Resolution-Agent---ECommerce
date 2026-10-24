"""SQLAlchemy models for Customer Support Resolution Agent."""
import datetime
import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, Index, UniqueConstraint, JSON, CheckConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

class UTCDateTime(TypeDecorator):
    """Store UTC consistently across SQLite and PostgreSQL timestamp columns."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value

class Base(DeclarativeBase):
    pass

class MockGatewayOperation(Base):
    __tablename__ = "mock_gateway_operations"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)

def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Customer(Base):
    __tablename__ = "customers"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("cust"))
    external_auth_subject: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="customer")
    tickets: Mapped[List["Ticket"]] = relationship("Ticket", back_populates="customer")

class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("ord"))
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False) # In minor units (cents)
    status: Mapped[str] = mapped_column(String(32), default="DELIVERED", nullable=False)
    items: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list) # [{sku, name, qty, price_minor}]
    order_date: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    delivery_date: Mapped[Optional[datetime.datetime]] = mapped_column(UTCDateTime, nullable=True)
    
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")
    returns: Mapped[List["ReturnRecord"]] = relationship("ReturnRecord", back_populates="order")
    payments: Mapped[List["PaymentRecord"]] = relationship("PaymentRecord", back_populates="order")
    tickets: Mapped[List["Ticket"]] = relationship("Ticket", back_populates="order")

class ReturnRecord(Base):
    __tablename__ = "return_records"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("ret"))
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("orders.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="REQUESTED", nullable=False)
    # Statuses: REQUESTED, IN_TRANSIT, RECEIVED, INSPECTION_PASSED, INSPECTION_FAILED, REJECTED
    tracking_number: Mapped[str] = mapped_column(String(64), nullable=True)
    carrier: Mapped[str] = mapped_column(String(64), nullable=True)
    return_reason: Mapped[str] = mapped_column(String(256), nullable=True)
    inspection_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    received_at: Mapped[Optional[datetime.datetime]] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    
    order: Mapped["Order"] = relationship("Order", back_populates="returns")

class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="payment_positive_amount"),
        CheckConstraint("refunded_amount_minor >= 0 AND reserved_refund_minor >= 0", name="payment_nonnegative_ledger"),
        CheckConstraint("refunded_amount_minor + reserved_refund_minor <= amount_minor", name="payment_balance_limit"),
        UniqueConstraint("order_id", name="payment_one_per_order"),
        CheckConstraint("status IN ('CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED', 'VOIDED', 'FAILED', 'CANCELED', 'EXPIRED')", name="payment_valid_status"),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("pay"))
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("orders.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False) # original charged amount
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    payment_method: Mapped[str] = mapped_column(String(64), default="CREDIT_CARD")
    status: Mapped[str] = mapped_column(String(32), default="CAPTURED") # CAPTURED, REFUNDED, PARTIALLY_REFUNDED, VOIDED, FAILED, CANCELED, EXPIRED
    refunded_amount_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_refund_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False) # pending approval/execution
    transaction_reference: Mapped[str] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    
    order: Mapped["Order"] = relationship("Order", back_populates="payments")
    
    @property
    def refundable_balance_minor(self) -> int:
        return max(0, self.amount_minor - self.refunded_amount_minor - self.reserved_refund_minor)

class Ticket(Base):
    __tablename__ = "tickets"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("tkt"))
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("customers.id"), nullable=False, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("orders.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="GENERAL")
    # Categories: ORDER_STATUS, REFUND_REQUEST, DAMAGED_ITEM, GENERAL
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    # Statuses: OPEN, INVESTIGATING, AWAITING_APPROVAL, RESOLVED, ESCALATED, CLOSED
    priority: Mapped[str] = mapped_column(String(32), default="MEDIUM")
    assigned_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    due_at: Mapped[Optional[datetime.datetime]] = mapped_column(UTCDateTime, nullable=True)
    evidence: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    customer_message: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    customer: Mapped["Customer"] = relationship("Customer", back_populates="tickets")
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="tickets")
    proposals: Mapped[List["RefundProposal"]] = relationship("RefundProposal", back_populates="ticket")

class RefundProposal(Base):
    __tablename__ = "refund_proposals"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="proposal_positive_amount"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'EXECUTED', 'INVALIDATED', 'DECLINED')", name="proposal_valid_status"),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("prop"))
    ticket_id: Mapped[str] = mapped_column(String(64), ForeignKey("tickets.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("orders.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, default=list)
    policy_refs: Mapped[List[str]] = mapped_column(JSON, default=list)
    missing_information: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    supersedes_proposal_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("refund_proposals.id"), nullable=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="proposals")
    approval: Mapped[Optional["Approval"]] = relationship("Approval", back_populates="proposal", uselist=False)
    operation: Mapped[Optional["RefundOperation"]] = relationship("RefundOperation", back_populates="proposal", uselist=False)
    superseded_proposals: Mapped[List["RefundProposal"]] = relationship("RefundProposal", backref="superseded_by", remote_side=[id])

class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("decision IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')", name="approval_valid_decision"),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("appr"))
    proposal_id: Mapped[str] = mapped_column(String(64), ForeignKey("refund_proposals.id"), nullable=False, unique=True, index=True)
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), default="PENDING") # PENDING, APPROVED, REJECTED, EXPIRED
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime.datetime]] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    
    proposal: Mapped["RefundProposal"] = relationship("RefundProposal", back_populates="approval")

class RefundOperation(Base):
    __tablename__ = "refund_operations"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="refund_one_operation_per_proposal"),
        CheckConstraint("amount_minor > 0", name="refund_positive_amount"),
        CheckConstraint("status IN ('CLAIMED', 'SENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'DECLINED', 'TIMED_OUT', 'UNKNOWN', 'PENDING_RECONCILIATION', 'MANUAL_REVIEW_REQUIRED')", name="refund_operation_valid_status"),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("op"))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(64), ForeignKey("refund_proposals.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    request_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="CLAIMED")
    # Statuses: CLAIMED, SENDING, PROCESSING, SUCCEEDED, FAILED, DECLINED, TIMED_OUT, UNKNOWN, PENDING_RECONCILIATION, MANUAL_REVIEW_REQUIRED
    gateway_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    proposal: Mapped["RefundProposal"] = relationship("RefundProposal", back_populates="operation")

class AuditEvent(Base):
    __tablename__ = "audit_events"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("aud"))
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False) # TICKET, PROPOSAL, APPROVAL, REFUND, WORKFLOW
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False) # CUSTOMER, AGENT, REVIEWER, SYSTEM
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow, index=True)

class PolicyChunk(Base):
    __tablename__ = "policy_chunks"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("pol_chk"))
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True) # e.g. refund_policy_v1
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False) # e.g. section_3
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding: Mapped[List[float]] = mapped_column(JSON, default=list) # Normalized dense vector
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=datetime.datetime.utcnow)
