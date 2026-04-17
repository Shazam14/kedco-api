"""add_credit_draws_and_app_settings

Revision ID: 0a2f7ed9b590
Revises: b3c4d5e6f7a8
Create Date: 2026-04-17 17:28:46.094063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0a2f7ed9b590'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('app_settings',
        sa.Column('key',        sa.String(length=100), nullable=False),
        sa.Column('value',      sa.Text(),             nullable=False),
        sa.Column('updated_by', sa.String(length=50),  nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )
    op.create_table('credit_draws',
        sa.Column('id',         sa.UUID(),             nullable=False),
        sa.Column('credit_id',  sa.UUID(),             nullable=False),
        sa.Column('amount',     sa.Float(),            nullable=False),
        sa.Column('notes',      sa.String(length=300), nullable=True),
        sa.Column('created_by', sa.String(length=50),  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['credit_id'], ['special_credits.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_credit_draws_credit_id', 'credit_draws', ['credit_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_credit_draws_credit_id', table_name='credit_draws')
    op.drop_table('credit_draws')
    op.drop_table('app_settings')
