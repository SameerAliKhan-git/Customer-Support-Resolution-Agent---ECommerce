"""Database leases coordinate workers without holding a transaction across I/O."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import update, delete
from sqlalchemy.exc import IntegrityError
from app.db.operations import ExecutionLease
from app.db.session import AsyncSessionLocal

@asynccontextmanager
async def lease(key: str, seconds: int = 90):
    owner = uuid4().hex
    now = datetime.utcnow()
    acquired = False
    async with AsyncSessionLocal() as db:
        try:
            db.add(ExecutionLease(id=key, owner=owner, expires_at=now + timedelta(seconds=seconds)))
            await db.commit()
            acquired = True
        except IntegrityError:
            await db.rollback()
            result = await db.execute(update(ExecutionLease).where(ExecutionLease.id == key,
                ExecutionLease.expires_at <= now).values(owner=owner, expires_at=now + timedelta(seconds=seconds)))
            await db.commit()
            acquired = result.rowcount == 1
    try:
        yield owner if acquired else None
    finally:
        if acquired:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(ExecutionLease).where(ExecutionLease.id == key, ExecutionLease.owner == owner))
                await db.commit()
