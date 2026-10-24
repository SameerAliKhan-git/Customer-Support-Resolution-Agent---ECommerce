"""Database session management with dual async/sync support for SQLite and PostgreSQL."""
from typing import AsyncGenerator
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base

# Setup async engine
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# Setup sync engine (used for migrations, background operations, and SQLite locking)
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=False,
    future=True,
)

# SQLite foreign keys enforcement
if "sqlite" in settings.SYNC_DATABASE_URL:
    @event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(async_engine.sync_engine, "connect")
    def set_async_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

def get_sync_db() -> Session:
    session = SyncSessionLocal()
    return session

async def init_db():
    """Create all tables asynchronously."""
    from app.db import operations
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def init_db_sync():
    """Create all tables synchronously."""
    Base.metadata.create_all(bind=sync_engine)
