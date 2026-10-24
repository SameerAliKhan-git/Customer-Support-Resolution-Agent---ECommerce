# -*- coding: utf-8 -*-
"""Alembic migration script template."""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "${rev}"
down_revision = ${down_revision}
branch_labels = ${branch_labels}
depends_on = ${depends_on}

def upgrade():
    pass

def downgrade():
    raise RuntimeError("Downgrades are not supported. Restore from a verified backup.")