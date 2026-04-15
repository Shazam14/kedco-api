"""add composite indexes on transactions for dashboard and report queries

Revision ID: 60c4ce04fda4
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15

The dashboard and report queries filter on:
  - (date, type)        → BUY/SELL splits per day
  - (date, cashier)     → per-cashier aggregates
  - (cashier, date)     → shift-level lookups

Single-column index on `date` already exists (index=True in model).
These composites avoid a second filter pass on the already-narrow date set.
"""
from alembic import op

revision = '60c4ce04fda4'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_transactions_date_type',
        'transactions',
        ['date', 'type'],
    )
    op.create_index(
        'ix_transactions_date_cashier',
        'transactions',
        ['date', 'cashier'],
    )


def downgrade() -> None:
    op.drop_index('ix_transactions_date_type',    table_name='transactions')
    op.drop_index('ix_transactions_date_cashier', table_name='transactions')
