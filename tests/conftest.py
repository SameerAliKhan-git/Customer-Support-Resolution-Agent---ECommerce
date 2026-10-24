import os
import sys
import asyncio
import tempfile
from pathlib import Path
import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_test_dir = tempfile.TemporaryDirectory(prefix="support-agent-tests-")
_db = (Path(_test_dir.name) / "test.db").as_posix()
if os.getenv("TEST_DATABASE_URL"):
    from sqlalchemy.engine import make_url
    test_url = make_url(os.environ["TEST_DATABASE_URL"])
    if not test_url.database.endswith("_test"):
        raise RuntimeError("Destructive test fixtures require a dedicated database ending in _test.")
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["SYNC_DATABASE_URL"] = test_url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    os.environ["CHECKPOINT_DATABASE_URL"] = test_url.set(drivername="postgresql").render_as_string(hide_password=False)
else:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db}"
    os.environ["SYNC_DATABASE_URL"] = f"sqlite:///{_db}"
    os.environ["CHECKPOINT_DATABASE_URL"] = f"sqlite:///{(Path(_test_dir.name) / 'checkpoints.db').as_posix()}"
os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_MODE"] = "demo"

@pytest.fixture(autouse=True)
async def isolated_database():
    from app.db.session import async_engine, init_db
    from app.db.models import Base
    from scripts.seed_data import seed
    from mock_services.payments.mock_payment_api import mock_payment_gateway
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await init_db()
    await seed()
    mock_payment_gateway.reset()
    yield
    from app.db.session import sync_engine
    sync_engine.dispose()
    await async_engine.dispose()
