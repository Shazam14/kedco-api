"""add php_capital_entries table

Revision ID: f3c4d5e6f9b0
Revises: f2b3c4d5e8a9
Create Date: 2026-05-04

Tracks owner-contributed PHP principal — the capital that funds the business.
Distinct from safe_movements (operational vault flow) and from bale (treasurer
movement). Running sum across all rows = current Capital PHP balance.

No opening balance — running net starts at zero on first entry.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f3c4d5e6f9b0'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'php_capital_entries',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('amount_php', sa.Float(), nullable=False),       # signed: + injection, - withdrawal
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('php_capital_entries')
