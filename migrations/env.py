"""Application schema migrations; LangGraph manages its own checkpoint schema."""
from alembic import context
from app.db.models import Base
from app.db.workflow_store import WorkflowRun
from app.services.eligibility import ProposalBinding
from app.db import operations
from app.db.session import sync_engine

if context.is_offline_mode():
    context.configure(url=str(sync_engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with sync_engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
        if connection.dialect.name == "sqlite":
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
            if violations:
                raise RuntimeError("Foreign key verification failed after migration.")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
