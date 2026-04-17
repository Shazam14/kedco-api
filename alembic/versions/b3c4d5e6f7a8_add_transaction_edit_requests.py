"""add transaction_edit_requests table

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-17 11:00:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transaction_edit_requests',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('txn_id',         sa.String(20),  nullable=False),
        sa.Column('txn_date',       sa.Date(),       nullable=False),
        sa.Column('requested_by',   sa.String(50),  nullable=False),
        sa.Column('current_values', postgresql.JSONB, nullable=False),
        sa.Column('proposed',       postgresql.JSONB, nullable=False),
        sa.Column('note',           sa.String(500), nullable=True),
        sa.Column('status',         sa.String(10),  nullable=False, server_default='PENDING'),
        sa.Column('reviewed_by',    sa.String(50),  nullable=True),
        sa.Column('reviewed_at',    sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_note', sa.String(500), nullable=True),
        sa.Column('created_at',     sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_edit_req_txn_id',       'transaction_edit_requests', ['txn_id'])
    op.create_index('ix_edit_req_requested_by', 'transaction_edit_requests', ['requested_by'])
    op.create_index('ix_edit_req_status',       'transaction_edit_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_edit_req_status',       'transaction_edit_requests')
    op.drop_index('ix_edit_req_requested_by', 'transaction_edit_requests')
    op.drop_index('ix_edit_req_txn_id',       'transaction_edit_requests')
    op.drop_table('transaction_edit_requests')
