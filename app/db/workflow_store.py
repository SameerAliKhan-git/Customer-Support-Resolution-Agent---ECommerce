"""Database-backed workflow snapshots survive process restarts."""
from sqlalchemy import String, JSON, select
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base
from app.db.session import AsyncSessionLocal


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[dict] = mapped_column(JSON)


async def save_state(state: dict):
    async with AsyncSessionLocal() as db:
        run = await db.get(WorkflowRun, state["run_id"])
        if run:
            run.state = dict(state)
        else:
            db.add(WorkflowRun(id=state["run_id"], ticket_id=state["ticket_id"], state=dict(state)))
        await db.commit()


async def load_state(run_id: str):
    async with AsyncSessionLocal() as db:
        run = await db.get(WorkflowRun, run_id)
        return dict(run.state) if run else None


async def find_run(ticket_id: str):
    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(WorkflowRun).where(WorkflowRun.ticket_id == ticket_id))).scalars().first()
        return run.id if run else None
