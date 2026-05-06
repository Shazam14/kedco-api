"""add misc_entries table

Revision ID: f6f7a8b9c2e3
Revises: f5e6f7a8b1d2
Create Date: 2026-05-06

Catch-all peso pool — entries that don't fit PHP Capital, Peso Ken, Branches,
or Treasurer. Subtracts from Available in the reconciliation formula.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f6f7a8b9c2e3'
down_revision: Union[str, Sequence[str], None] = 'f5e6f7a8b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'misc_entries',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('amount_php', sa.Float(), nullable=False),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('misc_entries')
