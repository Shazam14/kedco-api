from sqlalchemy import Column, String, Float, Date, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
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
    terminal_id       = Column(String(50), nullable=True)
    branch_id         = Column(String(20), nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    replenishments    = relationship("CashReplenishment", back_populates="shift", order_by="CashReplenishment.added_at")


class CashReplenishment(Base):
    __tablename__ = "cash_replenishments"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shift_id   = Column(UUID(as_uuid=True), ForeignKey("teller_shifts.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_php = Column(Float, nullable=False)
    note       = Column(String(300), nullable=True)
    # Where the cash came from. SAFE → also writes a paired safe_movement(-amount).
    source     = Column(String(20), nullable=False, server_default="TREASURER_FLOAT")
    added_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    shift      = relationship("TellerShift", back_populates="replenishments")


class SafeMovement(Base):
    """Single shared PHP vault. Signed amount: + deposit, - withdrawal."""
    __tablename__ = "safe_movements"

    id                       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount_php               = Column(Float, nullable=False)
    reason                   = Column(String(40), nullable=False)
    note                     = Column(String(300), nullable=True)
    actor_username           = Column(String(50), nullable=False)
    related_replenishment_id = Column(UUID(as_uuid=True), ForeignKey("cash_replenishments.id", ondelete="SET NULL"), nullable=True)
    related_dispatch_id      = Column(UUID(as_uuid=True), ForeignKey("rider_dispatches.id",     ondelete="SET NULL"), nullable=True)
    movement_date            = Column(Date, nullable=False, index=True)
    created_at               = Column(DateTime(timezone=True), server_default=func.now())


class TreasurerFloat(Base):
    __tablename__ = "treasurer_floats"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cashier_username   = Column(String(50), nullable=False, index=True)
    treasurer_username = Column(String(50), nullable=False)
    amount_php         = Column(Float, nullable=False)
    date               = Column(Date, nullable=False, index=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
