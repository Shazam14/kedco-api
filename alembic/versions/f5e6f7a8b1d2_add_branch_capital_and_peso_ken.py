"""add branch_capital and peso_ken_entries tables

Revision ID: f5e6f7a8b1d2
Revises: f4d5e6f7a0c1
Create Date: 2026-05-06

Two new tables that complete Ken's peso-capital reconciliation formula
(see project_peso_capital_model.md):

- branch_capital: per-branch peso allocation set by admin (config, not
  computed). Subtraction line in Available Peso Capital.
- peso_ken_entries: signed ledger of Ken's personal peso float (~300-500k)
  used for THAN payouts. Distinct from PhpCapitalEntry (owner principal).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f5e6f7a8b1d2'
down_revision: Union[str, Sequence[str], None] = 'f4d5e6f7a0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'branch_capital',
        sa.Column('branch_code', sa.String(20), primary_key=True),
        sa.Column('amount_php',  sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_by',  sa.String(50), nullable=False),
        sa.Column('updated_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        'peso_ken_entries',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('amount_php', sa.Float(), nullable=False),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('peso_ken_entries')
    op.drop_table('branch_capital')
