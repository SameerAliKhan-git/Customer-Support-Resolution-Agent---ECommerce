"""Durable work, leases, immutable policy versions and external event inbox."""
from datetime import datetime
from sqlalchemy import String, JSON, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base, UTCDateTime

class ExecutionLease(Base):
    __tablename__ = "execution_leases"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)

class WorkItem(Base):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="READY", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version", name="policy_version_identity"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[str] = mapped_column(String(10))
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)

class RequestReceipt(Base):
    __tablename__ = "request_receipts"
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64))

class ProviderEvent(Base):
    __tablename__ = "provider_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)

class RateBucket(Base):
    __tablename__ = "rate_buckets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
