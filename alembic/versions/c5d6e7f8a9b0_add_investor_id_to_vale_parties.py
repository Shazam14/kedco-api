"""add investor_id FK to vale_parties

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-05-11

Soft link from a vale party to a row in `investors`. Nullable: not every vale
party is an investor (could be a friend, family, or one-off lender). When set,
the UI shows a "★ INVESTOR" badge and Ken can see total exposure per investor
across capital + outstanding vale.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vale_parties',
        sa.Column('investor_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('investors.id', ondelete='SET NULL'),
                  nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column('vale_parties', 'investor_id')
