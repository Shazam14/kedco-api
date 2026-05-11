"""add destination column to inter_branch_outflows

Revision ID: a3b4c5d6e7f8
Revises: e2a3b4c5d6f8
Create Date: 2026-05-11

Splits drawer outflows by destination so PESO_KEN returns (treasurer →
Ken's float) share the table with BRANCH transfers (treasurer → other
branch). Existing rows default to 'BRANCH'.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'e2a3b4c5d6f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'inter_branch_outflows',
        sa.Column('destination', sa.String(20), nullable=False, server_default='BRANCH'),
    )


def downgrade() -> None:
    op.drop_column('inter_branch_outflows', 'destination')
