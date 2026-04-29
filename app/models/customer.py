from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class Customer(Base):
    """
    Loyal-customer master list. Optional FK on transactions —
    walk-ins/one-offs still use the free-text `transactions.customer` column.
    Dupes are reconciled by admin via merge: dupe gets `merged_into_id` set
    to the canonical row and `is_active=False`; all transaction FKs are
    repointed to the canonical id.
    """
    __tablename__ = "customers"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name           = Column(String(120), nullable=False, index=True)
    phone          = Column(String(20), nullable=True, index=True)
    notes          = Column(String(300), nullable=True)
    is_active      = Column(Boolean, default=True, nullable=False)
    merged_into_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    created_by     = Column(String(50), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
