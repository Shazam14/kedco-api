"""add banks table and payment mode to transactions

Revision ID: 36b81087af3d
Revises: 5424903a1a35
Create Date: 2026-04-13 08:36:27.201531

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '36b81087af3d'
down_revision: Union[str, Sequence[str], None] = '5424903a1a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── banks table ──────────────────────────────────────────────────────────
    op.create_table(
        'banks',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('name',       sa.String(100),   nullable=False),
        sa.Column('code',       sa.String(20),    nullable=False, unique=True),
        sa.Column('is_active',  sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('sort_order', sa.Integer(),     server_default='99'),
    )

    # ── create enum type first, then add columns ─────────────────────────────
    payment_mode_enum = sa.Enum(
        'CASH','GCASH','MAYA','SHOPEEPAY','BANK_TRANSFER','CHEQUE','OTHER',
        name='paymentmode'
    )
    payment_mode_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('transactions',
        sa.Column('payment_mode', payment_mode_enum, nullable=False, server_default='CASH')
    )
    op.add_column('transactions',
        sa.Column('bank_id', sa.Integer(), sa.ForeignKey('banks.id'), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('transactions', 'bank_id')
    op.drop_column('transactions', 'payment_mode')
    op.execute("DROP TYPE IF EXISTS paymentmode")
    op.drop_table('banks')
