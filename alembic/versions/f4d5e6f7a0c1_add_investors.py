"""add investors table

Revision ID: f4d5e6f7a0c1
Revises: f3c4d5e6f9b0
Create Date: 2026-05-05

Investor master data for the share estimator at /admin/investor-share.
Each row = one capital contributor + their monthly ROI rate; payments
themselves are not tracked in this table (settled off-system, often by
extracting equivalent FX stock).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f4d5e6f7a0c1'
down_revision: Union[str, Sequence[str], None] = 'f3c4d5e6f9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'investors',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',             sa.String(100), nullable=False),
        sa.Column('capital_php',      sa.Float(), nullable=False),
        sa.Column('monthly_rate_pct', sa.Float(), nullable=False),
        sa.Column('note',             sa.String(300), nullable=True),
        sa.Column('created_by',       sa.String(50), nullable=False),
        sa.Column('created_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('investors')
