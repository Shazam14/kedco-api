"""rider dispatch expand, rider borrows, payment status on transactions

Revision ID: 20599b41879f
Revises: 36b81087af3d
Create Date: 2026-04-13 08:47:24.539989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20599b41879f'
down_revision: Union[str, Sequence[str], None] = '36b81087af3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── new enums ─────────────────────────────────────────────────────────────
    dispatch_status_enum = sa.Enum('IN_FIELD', 'RETURNED', 'OFF', name='dispatchstatus')
    dispatch_status_enum.create(op.get_bind(), checkfirst=True)

    payment_status_enum = sa.Enum('RECEIVED', 'PENDING', name='paymentstatus')
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    # ── expand rider_dispatches ───────────────────────────────────────────────
    op.add_column('rider_dispatches', sa.Column('rider_username', sa.String(50),  nullable=True))
    op.add_column('rider_dispatches', sa.Column('return_time',    sa.String(10),  nullable=True))
    op.add_column('rider_dispatches', sa.Column('notes',          sa.String(200), nullable=True))
    op.add_column('rider_dispatches', sa.Column('dispatched_by',  sa.String(50),  nullable=True))
    op.execute("ALTER TABLE rider_dispatches ALTER COLUMN status TYPE dispatchstatus USING status::dispatchstatus")

    # ── rider_borrows table ───────────────────────────────────────────────────
    op.create_table(
        'rider_borrows',
        sa.Column('id',          sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dispatch_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rider_dispatches.id'), nullable=False),
        sa.Column('source_type', sa.String(10),  nullable=False),
        sa.Column('source_name', sa.String(100), nullable=False),
        sa.Column('amount_php',  sa.Float(),     nullable=False),
        sa.Column('is_returned', sa.String(1),   server_default='N'),
        sa.Column('notes',       sa.String(200), nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── transactions: payment_status + confirmation ───────────────────────────
    op.add_column('transactions',
        sa.Column('payment_status', payment_status_enum, nullable=False, server_default='RECEIVED')
    )
    op.add_column('transactions', sa.Column('confirmed_by', sa.String(50), nullable=True))
    op.add_column('transactions', sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('transactions', 'confirmed_at')
    op.drop_column('transactions', 'confirmed_by')
    op.drop_column('transactions', 'payment_status')
    op.drop_table('rider_borrows')
    op.drop_column('rider_dispatches', 'dispatched_by')
    op.drop_column('rider_dispatches', 'notes')
    op.drop_column('rider_dispatches', 'return_time')
    op.drop_column('rider_dispatches', 'rider_username')
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS dispatchstatus")
