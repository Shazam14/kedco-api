"""add audit_log table

Revision ID: a2b3c4d5e6f7
Revises: 63f1ff996f58
Create Date: 2026-04-17 10:00:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = '63f1ff996f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('table_name', sa.String(50), nullable=False),
        sa.Column('record_id',  sa.String(50), nullable=False),
        sa.Column('action',     sa.String(10), nullable=False),
        sa.Column('changed_by', sa.String(50), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('old_value',  postgresql.JSONB, nullable=True),
        sa.Column('new_value',  postgresql.JSONB, nullable=True),
        sa.Column('note',       sa.String(500),   nullable=True),
    )
    op.create_index('ix_audit_log_table_name', 'audit_log', ['table_name'])
    op.create_index('ix_audit_log_changed_by', 'audit_log', ['changed_by'])
    op.create_index('ix_audit_log_changed_at', 'audit_log', ['changed_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_changed_at', 'audit_log')
    op.drop_index('ix_audit_log_changed_by', 'audit_log')
    op.drop_index('ix_audit_log_table_name', 'audit_log')
    op.drop_table('audit_log')
