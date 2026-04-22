"""add_payment_tag_reference_date_to_transactions

Revision ID: dbce41124763
Revises: acecf955c9c0
Create Date: 2026-04-22 09:04:21.634987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dbce41124763'
down_revision: Union[str, Sequence[str], None] = 'acecf955c9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('payment_tag', sa.String(10), nullable=True))
    op.add_column('transactions', sa.Column('reference_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('transactions', 'reference_date')
    op.drop_column('transactions', 'payment_tag')
