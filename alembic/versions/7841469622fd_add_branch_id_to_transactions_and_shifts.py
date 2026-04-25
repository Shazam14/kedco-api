"""add_branch_id_to_transactions_and_shifts

Revision ID: 7841469622fd
Revises: 752b87bb09d2
Create Date: 2026-04-25

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '7841469622fd'
down_revision: Union[str, Sequence[str], None] = '752b87bb09d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('branch_id', sa.String(20), nullable=True))
    op.add_column('teller_shifts', sa.Column('branch_id', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('teller_shifts', 'branch_id')
    op.drop_column('transactions', 'branch_id')
