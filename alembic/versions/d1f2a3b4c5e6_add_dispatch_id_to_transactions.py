"""add dispatch_id to transactions

Revision ID: d1f2a3b4c5e6
Revises: c1e3a5b7d9f2
Create Date: 2026-05-08

Scopes rider transactions to the dispatch they were created under, so a
re-dispatch on the same day starts the rider's screen at zero. Also lets the
treasurer-confirm flow filter PENDING by dispatch.

Nullable on existing rows; backfilled by scripts/backfill_rider_dispatch_id.py.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd1f2a3b4c5e6'
down_revision: Union[str, Sequence[str], None] = 'c1e3a5b7d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'transactions',
        sa.Column('dispatch_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_transactions_dispatch_id',
        'transactions', 'rider_dispatches',
        ['dispatch_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_transactions_dispatch_id',
        'transactions', ['dispatch_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_transactions_dispatch_id', table_name='transactions')
    op.drop_constraint('fk_transactions_dispatch_id', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'dispatch_id')
