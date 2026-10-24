"""Proposal supersession and status check constraints.

Revision ID: 0003_proposal_supersession
Revises: 0002_reliability
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_proposal_supersession'
down_revision = '0002_reliability'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('refund_proposals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supersedes_proposal_id', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_refund_proposals_supersedes_proposal_id'), ['supersedes_proposal_id'], unique=False)
        batch_op.create_foreign_key('fk_refund_proposals_supersedes_proposal_id', 'refund_proposals', ['supersedes_proposal_id'], ['id'])
        batch_op.create_check_constraint('proposal_valid_status', "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'EXECUTED', 'INVALIDATED', 'DECLINED')")

    with op.batch_alter_table('payment_records', schema=None) as batch_op:
        batch_op.create_check_constraint('payment_valid_status', "status IN ('CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED', 'VOIDED', 'FAILED', 'CANCELED', 'EXPIRED')")

    with op.batch_alter_table('approvals', schema=None) as batch_op:
        batch_op.create_check_constraint('approval_valid_decision', "decision IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')")

    with op.batch_alter_table('refund_operations', schema=None) as batch_op:
        batch_op.create_check_constraint('refund_operation_valid_status', "status IN ('CLAIMED', 'SENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'DECLINED', 'TIMED_OUT', 'UNKNOWN', 'PENDING_RECONCILIATION', 'MANUAL_REVIEW_REQUIRED')")

def downgrade():
    raise RuntimeError('Restore a verified backup to roll back ledger schema changes.')
