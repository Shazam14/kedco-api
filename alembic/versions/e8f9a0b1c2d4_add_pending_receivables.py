"""add pending_receivables table

Revision ID: e8f9a0b1c2d4
Revises: d7f8a9b0c1d3
Create Date: 2026-05-20

Standalone ledger of pending receivables (cheques, GCash, PNB transfers,
bank deposits) grouped by destination bank inbox (GPO / CBC / MBTC PB).
Lives outside the FX txn flow — these are stale receivables Merly tracks
in her notebook, not slices on existing SELLs.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e8f9a0b1c2d4'
down_revision: Union[str, Sequence[str], None] = 'd7f8a9b0c1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pending_receivables',
        sa.Column('id',            postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('customer_name', sa.String(120), nullable=False),
        sa.Column('amount_php',    sa.Float(), nullable=False),
        sa.Column('method',        sa.String(20), nullable=False, server_default='UNKNOWN'),
        sa.Column('bank_account',  sa.String(20), nullable=False),
        sa.Column('entry_date',    sa.Date(), nullable=True, index=True),
        sa.Column('status',        sa.String(20), nullable=False, server_default='PENDING', index=True),
        sa.Column('note',          sa.String(300), nullable=True),
        sa.Column('cleared_at',    sa.DateTime(timezone=True), nullable=True),
        sa.Column('cleared_by',    sa.String(50), nullable=True),
        sa.Column('created_by',    sa.String(50), nullable=False),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('pending_receivables')
