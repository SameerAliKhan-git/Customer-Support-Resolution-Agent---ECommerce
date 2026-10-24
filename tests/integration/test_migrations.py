"""Tests for database migrations, schema drift, and proposal supersession."""
import tempfile
from pathlib import Path
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, select, inspect
import app.db.session
from app.db.models import Base, RefundProposal
from app.db.session import AsyncSessionLocal
from app.services.approval_service import approval_service

def test_alembic_migration_and_no_drift():
    """Verify that an empty database upgrades cleanly to head and has zero schema drift."""
    original_engine = app.db.session.sync_engine
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fresh_migration.db"
        test_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        app.db.session.sync_engine = test_engine

        try:
            cfg = Config("alembic.ini")
            # Upgrade fresh DB through all migrations (0001, 0002, 0003) to head
            command.upgrade(cfg, "head")

            # Check that columns and constraints exist
            inspector = inspect(test_engine)
            columns = {col["name"] for col in inspector.get_columns("refund_proposals")}
            assert "supersedes_proposal_id" in columns
            assert "status" in columns

            # command.check raises CommandError if any drift is detected between ORM and DB
            command.check(cfg)
        finally:
            test_engine.dispose()
            app.db.session.sync_engine = original_engine

async def test_proposal_supersession_linking():
    """Verify that a superseded proposal correctly links to its prior proposal."""
    async with AsyncSessionLocal() as db:
        # Create an initial proposal
        prop1 = await approval_service.create_proposal(
            db=db,
            ticket_id="tkt_1001",
            order_id="ord_1001",
            customer_id="cust_1001",
            amount_minor=5000,
            reason="Initial defect reason",
            evidence_refs=[],
            policy_refs=["refund_policy_v1:section_3"],
        )
        assert prop1.id is not None
        assert prop1.supersedes_proposal_id is None

        # Terminalize prop1 to allow supersession
        prop1.status = "DECLINED"
        await db.commit()

        # Create superseding proposal
        prop2 = await approval_service.create_proposal(
            db=db,
            ticket_id="tkt_1001",
            order_id="ord_1001",
            customer_id="cust_1001",
            amount_minor=4000,
            reason="Superseding revised claim",
            evidence_refs=[],
            policy_refs=["refund_policy_v1:section_3"],
            supersedes_proposal_id=prop1.id,
        )
        assert prop2.id is not None
        assert prop2.supersedes_proposal_id == prop1.id

        # Reload from db and verify relationship
        reloaded = (await db.execute(select(RefundProposal).where(RefundProposal.id == prop2.id))).scalar_one()
        assert reloaded.supersedes_proposal_id == prop1.id
