"""add is_demo to users and seed demo accounts

Revision ID: a1b2c3d4e5f6
Revises: 20599b41879f
Create Date: 2026-04-15 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import table, column, String, Boolean


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '20599b41879f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEMO_USERS = [
    {"username": "admintest",   "full_name": "Admin (Demo)",   "role": "admin"},
    {"username": "cashiertest", "full_name": "Cashier (Demo)", "role": "cashier"},
    {"username": "ridertest",   "full_name": "Rider (Demo)",   "role": "rider"},
    {"username": "devtest",     "full_name": "Dev (Demo)",     "role": "admin"},
]

DEMO_PASSWORD_HASH = (
    # bcrypt hash of "Demo@2026!" — pre-computed so the migration has no runtime deps
    "$2b$12$9v.2PqpxqF7Yn9VVEFmQcOa5wQk3E8LY7I0RcBkAJZHfzMuO3WXfi"
)


def upgrade() -> None:
    # ── 1. Add column ───────────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
    )

    # ── 2. Seed demo accounts ───────────────────────────────────────────────
    bind = op.get_bind()
    session = Session(bind=bind)

    users_t = table(
        "users",
        column("username", String),
        column("full_name", String),
        column("password_hash", String),
        column("role", String),
        column("is_active", Boolean),
        column("is_demo", Boolean),
    )

    for u in DEMO_USERS:
        exists = session.execute(
            sa.text("SELECT 1 FROM users WHERE username = :username"),
            {"username": u["username"]},
        ).fetchone()
        if not exists:
            op.bulk_insert(users_t, [{
                "username":      u["username"],
                "full_name":     u["full_name"],
                "password_hash": DEMO_PASSWORD_HASH,
                "role":          u["role"],
                "is_active":     True,
                "is_demo":       True,
            }])

    session.close()


def downgrade() -> None:
    # Remove demo users then drop column
    op.execute(
        "DELETE FROM users WHERE username IN "
        "('admintest', 'cashiertest', 'ridertest', 'devtest')"
    )
    op.drop_column("users", "is_demo")
