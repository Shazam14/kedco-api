"""add shift_id FK on expenses + backfill from recorded_by/created_at window

Revision ID: f2b3c4d5e8a9
Revises: f1a2b3c4d5e7
Create Date: 2026-05-02

Cashiers should only see expenses logged during their currently OPEN shift.
Once the shift closes, those rows are no longer in the cashier's view (admins
still see everything). Stamping shift_id at create time makes the per-shift
tally authoritative — same pattern as cash_replenishments.shift_id.

Backfill matches each existing expense to the shift it was logged under by
the recorded_by + created_at window. Rows with no match (orphan / shift
never opened) keep shift_id NULL — admin still sees them; cashier never does.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f2b3c4d5e8a9'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'expenses',
        sa.Column(
            'shift_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('teller_shifts.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_expenses_shift_id', 'expenses', ['shift_id'])

    # Backfill: for each expense pick the most recent shift whose cashier
    # matches recorded_by AND whose [opened_at, closed_at OR future] window
    # contains the expense's created_at. Multiple matches → pick latest open.
    op.execute("""
        UPDATE expenses e
        SET shift_id = (
            SELECT ts.id
            FROM teller_shifts ts
            WHERE ts.cashier = e.recorded_by
              AND e.created_at >= ts.opened_at
              AND e.created_at < COALESCE(ts.closed_at, NOW() + interval '1 day')
            ORDER BY ts.opened_at DESC
            LIMIT 1
        )
        WHERE e.shift_id IS NULL
    """)


def downgrade() -> None:
    op.drop_index('ix_expenses_shift_id', table_name='expenses')
    op.drop_column('expenses', 'shift_id')
