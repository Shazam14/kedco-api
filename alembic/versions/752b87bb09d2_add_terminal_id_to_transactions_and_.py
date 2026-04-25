"""add_terminal_id_to_transactions_and_shifts

Revision ID: 752b87bb09d2
Revises: c9d8e7f6a5b4
Create Date: 2026-04-25 10:26:48.197562

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '752b87bb09d2'
down_revision: Union[str, Sequence[str], None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('terminal_id', sa.String(50), nullable=True))
    op.add_column('teller_shifts', sa.Column('terminal_id', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('teller_shifts', 'terminal_id')
    op.drop_column('transactions', 'terminal_id')
