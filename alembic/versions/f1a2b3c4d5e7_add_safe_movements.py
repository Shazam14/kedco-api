"""add safe_movements table + source column on cash_replenishments

Revision ID: f1a2b3c4d5e7
Revises: e7f8a9b0c1d2
Create Date: 2026-05-02

The "safe" is a single shared PHP vault for the business. Treasurers pull cash
from it to fund cashier replenishments and rider dispatches. Tracking it
honestly stops these movements from being mis-counted as fresh capital.

No opening balance — running net starts at zero on first movement.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f1a2b3c4d5e7'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'safe_movements',
        sa.Column('id',                       postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('amount_php',               sa.Float(), nullable=False),  # signed: + deposit, - withdrawal
        sa.Column('reason',                   sa.String(40), nullable=False),
        sa.Column('note',                     sa.String(300), nullable=True),
        sa.Column('actor_username',           sa.String(50), nullable=False),
        sa.Column('related_replenishment_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('cash_replenishments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('related_dispatch_id',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rider_dispatches.id', ondelete='SET NULL'), nullable=True),
        sa.Column('movement_date',            sa.Date(), nullable=False, index=True),
        sa.Column('created_at',               sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        'cash_replenishments',
        sa.Column('source', sa.String(20), nullable=False, server_default='TREASURER_FLOAT'),
    )


def downgrade() -> None:
    op.drop_column('cash_replenishments', 'source')
    op.drop_table('safe_movements')
