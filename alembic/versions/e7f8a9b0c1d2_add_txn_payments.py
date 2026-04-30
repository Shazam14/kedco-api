"""add txn_payments table (phase 1 of split-payments: schema + backfill, no behavior change)

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-04-30

One row per payment slice on a transaction. Phase 1 backfills exactly one slice
per existing txn mirroring its current single-method payment, so reads/writes
that still go through transactions.payment_mode/payment_status keep working.
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM as PgEnum

revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reuse the existing pg enum types (paymentmode, paymentstatus) — don't recreate.
    payment_mode_enum = PgEnum(
        'CASH', 'GCASH', 'MAYA', 'SHOPEEPAY', 'BANK_TRANSFER', 'CHEQUE', 'OTHER',
        name='paymentmode', create_type=False,
    )
    payment_status_enum = PgEnum(
        'RECEIVED', 'PENDING',
        name='paymentstatus', create_type=False,
    )

    op.create_table(
        'txn_payments',
        sa.Column('id',           UUID(as_uuid=True), primary_key=True),
        sa.Column('txn_id',       sa.String(20),
                  sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('method',       payment_mode_enum, nullable=False),
        sa.Column('amount_php',   sa.Float(), nullable=False),
        sa.Column('status',       payment_status_enum, nullable=False, server_default='RECEIVED'),
        sa.Column('reference_no', sa.String(60),  nullable=True),
        sa.Column('received_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirmed_by', sa.String(50),  nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_txn_payments_txn_id', 'txn_payments', ['txn_id'])
    op.create_index('ix_txn_payments_status', 'txn_payments', ['status'])

    # Backfill: mirror each transaction as a single payment slice.
    op.execute("""
        INSERT INTO txn_payments
            (id, txn_id, method, amount_php, status,
             received_at, confirmed_by, created_at)
        SELECT
            gen_random_uuid(),
            id,
            payment_mode,
            php_amt,
            payment_status,
            CASE WHEN payment_status = 'RECEIVED'
                 THEN COALESCE(confirmed_at, created_at)
                 ELSE NULL
            END,
            confirmed_by,
            COALESCE(created_at, NOW())
        FROM transactions
    """)


def downgrade() -> None:
    op.drop_index('ix_txn_payments_status', table_name='txn_payments')
    op.drop_index('ix_txn_payments_txn_id', table_name='txn_payments')
    op.drop_table('txn_payments')
