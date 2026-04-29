"""add credit ledger entries

Revision ID: d4e5f6a7b8c9
Revises: e3f4a5b6c7d8
Create Date: 2026-04-29

Adds a per-row ledger for Apple-style revolving credits — mirrors the
Excel ledger Ken keeps (DATE/TIME/DESC/PALOD/THAN/BAYAD/BALANCE).
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'credit_ledger_entries',
        sa.Column('id',          UUID(as_uuid=True), primary_key=True),
        sa.Column('credit_id',   UUID(as_uuid=True), sa.ForeignKey('special_credits.id'), nullable=False),
        sa.Column('date',        sa.Date(), nullable=False),
        sa.Column('time',        sa.String(20),  nullable=True),
        sa.Column('description', sa.String(300), nullable=True),
        sa.Column('palod',       sa.Float(), nullable=False, server_default='0'),
        sa.Column('than',        sa.Float(), nullable=False, server_default='0'),
        sa.Column('bayad',       sa.Float(), nullable=False, server_default='0'),
        sa.Column('balance',     sa.Float(), nullable=True),
        sa.Column('created_by',  sa.String(50), nullable=False),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_credit_ledger_entries_credit_id', 'credit_ledger_entries', ['credit_id'])
    op.create_index('ix_credit_ledger_entries_date',      'credit_ledger_entries', ['date'])


def downgrade() -> None:
    op.drop_index('ix_credit_ledger_entries_date',      table_name='credit_ledger_entries')
    op.drop_index('ix_credit_ledger_entries_credit_id', table_name='credit_ledger_entries')
    op.drop_table('credit_ledger_entries')
