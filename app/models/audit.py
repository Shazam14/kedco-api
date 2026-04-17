from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name = Column(String(50), nullable=False, index=True)
    record_id  = Column(String(50), nullable=False)
    action     = Column(String(10), nullable=False)   # CREATE | UPDATE | DELETE
    changed_by = Column(String(50), nullable=False, index=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    old_value  = Column(JSONB, nullable=True)
    new_value  = Column(JSONB, nullable=True)
    note       = Column(String(500), nullable=True)
