"""add official_rate and referrer to transactions

Revision ID: e1f2a3b4c5d6
Revises: d8c1d8da3385
Create Date: 2026-04-22

official_rate — the admin-set rate at time of transaction (auto-captured server-side).
               Used to compute cashier/referrer commission when actual rate exceeds it.
referrer      — optional tour guide or referral source name.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'd8c1d8da3385'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('official_rate', sa.Float(), nullable=True))
    op.add_column('transactions', sa.Column('referrer',      sa.String(100), nullable=True))


def downgrade():
    op.drop_column('transactions', 'referrer')
    op.drop_column('transactions', 'official_rate')
