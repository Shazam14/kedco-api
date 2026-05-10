"""add inter_branch_outflows table

Revision ID: e2a3b4c5d6f8
Revises: d1f2a3b4c5e6
Create Date: 2026-05-08

Drawer-negative inter-branch transfers — treasurer sends cash to another
branch. Mirrors cash_replenishments shape but represents an outflow, not
a replenishment, so it's stored in its own table.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e2a3b4c5d6f8'
down_revision: Union[str, Sequence[str], None] = 'd1f2a3b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inter_branch_outflows',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('shift_id',   postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('teller_shifts.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('amount_php', sa.Float(), nullable=False),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('sent_at',    sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('inter_branch_outflows')
