"""merge_three_heads

Revision ID: acecf955c9c0
Revises: 0a2f7ed9b590, b2c3d4e5f6a7, e1f2a3b4c5d6
Create Date: 2026-04-22 09:04:16.422318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acecf955c9c0'
down_revision: Union[str, Sequence[str], None] = ('0a2f7ed9b590', 'b2c3d4e5f6a7', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
