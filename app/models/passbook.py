from sqlalchemy import Column, String, Float, Date, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PassbookEntry(Base):
    __tablename__ = "passbook_entries"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bank_id        = Column(Integer, ForeignKey("banks.id"), nullable=False, index=True)
    amount         = Column(Float, nullable=False)          # always positive, deposits only
    deposited_date = Column(Date, nullable=False)
    logged_by      = Column(String(50), nullable=False)     # username of cashier/admin
    notes          = Column(String(300), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
