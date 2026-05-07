"""add cleared_at and cleared_by to txn_payments

Revision ID: c1e3a5b7d9f2
Revises: f6f7a8b9c2e3
Create Date: 2026-05-06

Cheque-clear flow (Phase 2.2 of treasurer screen v2). A CHEQUE TxnPayment is
issued PENDING; the treasurer manually clicks ✓ once the bank confirms the
cheque cleared, stamping cleared_at + cleared_by. Only cleared cheques count
toward the treasurer drawer's `cheques_cleared_php`.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c1e3a5b7d9f2'
down_revision: Union[str, Sequence[str], None] = 'f6f7a8b9c2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('txn_payments', sa.Column('cleared_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('txn_payments', sa.Column('cleared_by', sa.String(50), nullable=True))
    op.create_index('ix_txn_payments_cleared_at', 'txn_payments', ['cleared_at'])


def downgrade() -> None:
    op.drop_index('ix_txn_payments_cleared_at', table_name='txn_payments')
    op.drop_column('txn_payments', 'cleared_by')
    op.drop_column('txn_payments', 'cleared_at')
