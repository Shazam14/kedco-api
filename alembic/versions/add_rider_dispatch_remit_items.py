"""add rider_dispatch_items and rider_remit_items tables

Revision ID: b2c3d4e5f6a7
Revises: 20599b41879f
Create Date: 2026-04-18 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '20599b41879f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rider_dispatch_items',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dispatch_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rider_dispatches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('currency',    sa.String(10), nullable=False),
        sa.Column('amount',      sa.Float(),    nullable=False),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        'rider_remit_items',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dispatch_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rider_dispatches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('currency',    sa.String(10), nullable=False),
        sa.Column('amount',      sa.Float(),    nullable=False),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.alter_column('rider_dispatches', 'cash_php', nullable=True)


def downgrade() -> None:
    op.drop_table('rider_remit_items')
    op.drop_table('rider_dispatch_items')
    op.alter_column('rider_dispatches', 'cash_php', nullable=False)
