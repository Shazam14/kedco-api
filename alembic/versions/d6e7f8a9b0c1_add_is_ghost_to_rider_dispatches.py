"""add is_ghost flag to rider_dispatches

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-05-18

Ghost dispatches are auto-created when a rider does a SELL without an active
dispatch. Carries no PHP. Admin's POST /dispatches promotes a ghost (flips the
flag and fills cash_php). BUY is gated against is_ghost=True so the rider sees
a "need dispatch" message instead of trying to spend nonexistent PHP.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'rider_dispatches',
        sa.Column('is_ghost', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('rider_dispatches', 'is_ghost')
