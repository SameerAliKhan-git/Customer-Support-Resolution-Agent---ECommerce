"""Official durable LangGraph savers, separate from application tables."""
from contextlib import asynccontextmanager
from sqlalchemy.engine import make_url
from app.config import settings
_postgres_ready = False

@asynccontextmanager
async def checkpoint_store():
    global _postgres_ready
    url = settings.CHECKPOINT_DATABASE_URL
    if url.startswith("sqlite"):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(make_url(url).database) as saver:
            await saver.setup()
            yield saver
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            if not _postgres_ready:
                await saver.setup()
                _postgres_ready = True
            yield saver
