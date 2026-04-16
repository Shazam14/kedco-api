"""add special_credits and credit_installments tables

Revision ID: f1a2b3c4d5e6
Revises: 8b21747c27c4
Create Date: 2026-04-16

Special customer credit tracking:
  - special_credits      — the loan record (UPFRONT or INSTALLMENT)
  - credit_installments  — payment schedule (1 slot for UPFRONT, N for INSTALLMENT)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "8b21747c27c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "special_credits",
        sa.Column("id",             UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_name",  sa.String(100), nullable=False),
        sa.Column("currency_code",  sa.String(10),  nullable=False),
        sa.Column("principal",      sa.Float,       nullable=False),
        sa.Column("interest",       sa.Float,       nullable=False),
        sa.Column("credit_type",    sa.Enum("UPFRONT", "INSTALLMENT", name="credittype"),   nullable=False),
        sa.Column("status",         sa.Enum("ACTIVE", "COMPLETED", "CANCELLED", name="creditstatus"), nullable=False, server_default="ACTIVE"),
        sa.Column("disbursed_date", sa.Date,        nullable=False),
        sa.Column("notes",          sa.String(300), nullable=True),
        sa.Column("created_by",     sa.String(50),  nullable=False),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",     sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    op.create_table(
        "credit_installments",
        sa.Column("id",              UUID(as_uuid=True), primary_key=True),
        sa.Column("credit_id",       UUID(as_uuid=True), sa.ForeignKey("special_credits.id"), nullable=False),
        sa.Column("installment_no",  sa.Integer,  nullable=False),
        sa.Column("due_date",        sa.Date,     nullable=False),
        sa.Column("amount",          sa.Float,    nullable=False),
        sa.Column("paid_at",         sa.Date,     nullable=True),
        sa.Column("received_by",     sa.String(50), nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_credit_installments_credit_id", "credit_installments", ["credit_id"])
    op.create_index("ix_special_credits_disbursed_date", "special_credits", ["disbursed_date"])
    op.create_index("ix_special_credits_status", "special_credits", ["status"])


def downgrade() -> None:
    op.drop_index("ix_credit_installments_credit_id", table_name="credit_installments")
    op.drop_index("ix_special_credits_disbursed_date", table_name="special_credits")
    op.drop_index("ix_special_credits_status", table_name="special_credits")
    op.drop_table("credit_installments")
    op.drop_table("special_credits")
    op.execute("DROP TYPE IF EXISTS credittype")
    op.execute("DROP TYPE IF EXISTS creditstatus")
