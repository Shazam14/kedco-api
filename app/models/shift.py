from sqlalchemy import Column, String, Float, Date, DateTime, Enum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class ShiftStatus(str, enum.Enum):
    OPEN   = "OPEN"
    CLOSED = "CLOSED"


class TellerShift(Base):
    """
    One row per cashier per shift.
    Tracks opening cash float, all PHP in/out during the shift,
    and the declared closing cash for reconciliation.
    """
    __tablename__ = "teller_shifts"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date              = Column(Date, nullable=False, index=True)
    cashier           = Column(String(50), nullable=False, index=True)
    cashier_name      = Column(String(100), nullable=False)
    status            = Column(Enum(ShiftStatus), default=ShiftStatus.OPEN, nullable=False)
    opened_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at         = Column(DateTime(timezone=True), nullable=True)
    opening_cash_php  = Column(Float, nullable=False)           # starting drawer float
    closing_cash_php  = Column(Float, nullable=True)            # declared at close
    expected_cash_php = Column(Float, nullable=True)            # computed: opening + SELLs - BUYs
    cash_variance     = Column(Float, nullable=True)            # closing_cash - expected_cash
    notes             = Column(String(300), nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
