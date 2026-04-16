"""merge heads

Revision ID: d8c1d8da3385
Revises: 60c4ce04fda4, f1a2b3c4d5e6
Create Date: 2026-04-16 16:00:23.475183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8c1d8da3385'
down_revision: Union[str, Sequence[str], None] = ('60c4ce04fda4', 'f1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
