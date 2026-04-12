"""add supervisor rider roles and branch column

Revision ID: 5424903a1a35
Revises: 9240981df8ac
Create Date: 2026-04-12 17:49:33.062201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5424903a1a35'
down_revision: Union[str, Sequence[str], None] = '9240981df8ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new enum values — PostgreSQL requires ALTER TYPE, not supported by autogenerate
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'supervisor'")
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'rider'")
    op.add_column('users', sa.Column('branch', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Note: PostgreSQL does not support removing enum values — only branch column removed
    op.drop_column('users', 'branch')
