"""add rider_dispatch_topups table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-29 03:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rider_dispatch_topups',
        sa.Column('id',            postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dispatch_id',   postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rider_dispatches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount_php',    sa.Float(), nullable=False),
        sa.Column('time',          sa.String(10), nullable=True),
        sa.Column('dispatched_by', sa.String(50), nullable=True),
        sa.Column('notes',         sa.String(200), nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('rider_dispatch_topups')
