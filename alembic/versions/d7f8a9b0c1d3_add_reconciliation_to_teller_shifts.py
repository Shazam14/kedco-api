"""add reconciliation note/status to teller_shifts

Revision ID: d7f8a9b0c1d3
Revises: d6e7f8a9b0c1
Create Date: 2026-05-20

GAP_CHECK Phase 2: lets admin/treasurer annotate the variance between expected
and declared closing peso, and track whether it's been reviewed. Surfaces on
/admin/report GAP_CHECK strip so gaps stop sitting as anonymous amber numbers.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd7f8a9b0c1d3'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'teller_shifts',
        sa.Column('reconciliation_note', sa.Text(), nullable=True),
    )
    op.add_column(
        'teller_shifts',
        sa.Column(
            'reconciliation_status',
            sa.String(20),
            nullable=False,
            server_default='PENDING',
        ),
    )


def downgrade() -> None:
    op.drop_column('teller_shifts', 'reconciliation_status')
    op.drop_column('teller_shifts', 'reconciliation_note')
