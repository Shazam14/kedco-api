"""add cash replenishments table

Revision ID: c9d8e7f6a5b4
Revises: f64fd4652e14
Create Date: 2026-04-22
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, Sequence[str], None] = 'f64fd4652e14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cash_replenishments',
        sa.Column('id',         UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('shift_id',   UUID(as_uuid=True), sa.ForeignKey('teller_shifts.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('amount_php', sa.Float, nullable=False),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('added_at',   sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('cash_replenishments')
