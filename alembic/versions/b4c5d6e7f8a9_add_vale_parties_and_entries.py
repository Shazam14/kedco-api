"""add vale_parties and vale_entries tables

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-05-11

VALE = cash received from (or paid back to) an external party (typically
an investor). Two tables mirror the peso_ken pattern but scoped to a
party FK so multiple lenders can be tracked with running balances.

- vale_parties: master list of investors / IOU counterparts
- vale_entries: signed ledger per party (paired with cash_replenishments
  source='VALE' or inter_branch_outflows destination='VALE')
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vale_parties',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',       sa.String(80), nullable=False, unique=True, index=True),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('is_active',  sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        'vale_entries',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('party_id',   postgresql.UUID(as_uuid=True),
                                sa.ForeignKey('vale_parties.id', ondelete='RESTRICT'),
                                nullable=False, index=True),
        sa.Column('amount_php', sa.Float(), nullable=False),
        sa.Column('note',       sa.String(300), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False, index=True),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('vale_entries')
    op.drop_table('vale_parties')
