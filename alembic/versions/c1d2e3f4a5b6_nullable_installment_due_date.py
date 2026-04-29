"""nullable installment due_date

Revision ID: c1d2e3f4a5b6
Revises: 0a2f7ed9b590
Create Date: 2026-04-27

Due dates on credit installments are not enforced — Apple (and similar customers)
repay whenever, not on a fixed schedule.
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = '7841469622fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('credit_installments', 'due_date', existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    op.alter_column('credit_installments', 'due_date', existing_type=sa.Date(), nullable=False)
