"""add customers table and transactions.customer_id FK

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-29 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'customers',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',           sa.String(120), nullable=False),
        sa.Column('phone',          sa.String(20),  nullable=True),
        sa.Column('notes',          sa.String(300), nullable=True),
        sa.Column('is_active',      sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('merged_into_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id'), nullable=True),
        sa.Column('created_by',     sa.String(50), nullable=True),
        sa.Column('created_at',     sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_customers_name',  'customers', ['name'])
    op.create_index('ix_customers_phone', 'customers', ['phone'])

    op.add_column(
        'transactions',
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id'), nullable=True),
    )
    op.create_index('ix_transactions_customer_id', 'transactions', ['customer_id'])


def downgrade() -> None:
    op.drop_index('ix_transactions_customer_id', table_name='transactions')
    op.drop_column('transactions', 'customer_id')
    op.drop_index('ix_customers_phone', table_name='customers')
    op.drop_index('ix_customers_name', table_name='customers')
    op.drop_table('customers')
