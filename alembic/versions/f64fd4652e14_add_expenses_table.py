"""add_expenses_table

Revision ID: f64fd4652e14
Revises: dbce41124763
Create Date: 2026-04-22 09:24:36.102711

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f64fd4652e14'
down_revision: Union[str, Sequence[str], None] = 'dbce41124763'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'expenses',
        sa.Column('id',          sa.String(36),  primary_key=True),
        sa.Column('date',        sa.Date(),       nullable=False),
        sa.Column('amount_php',  sa.Float(),      nullable=False),
        sa.Column('category',    sa.String(30),   nullable=False),
        sa.Column('description', sa.String(200),  nullable=True),
        sa.Column('recorded_by', sa.String(50),   nullable=False),
        sa.Column('status',      sa.String(10),   nullable=False, server_default='PENDING'),
        sa.Column('approved_by', sa.String(50),   nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_expenses_date', 'expenses', ['date'])


def downgrade() -> None:
    op.drop_index('ix_expenses_date', table_name='expenses')
    op.drop_table('expenses')
