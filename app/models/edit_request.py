from sqlalchemy import Column, String, Date, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class EditRequestStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TransactionEditRequest(Base):
    __tablename__ = "transaction_edit_requests"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    txn_id         = Column(String(20), nullable=False, index=True)
    txn_date       = Column(Date, nullable=False)
    requested_by   = Column(String(50), nullable=False, index=True)
    current_values = Column(JSONB, nullable=False)
    proposed       = Column(JSONB, nullable=False)
    note           = Column(String(500), nullable=True)
    status         = Column(Enum(EditRequestStatus), default=EditRequestStatus.PENDING, nullable=False, index=True)
    reviewed_by    = Column(String(50), nullable=True)
    reviewed_at    = Column(DateTime(timezone=True), nullable=True)
    rejection_note = Column(String(500), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
