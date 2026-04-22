from sqlalchemy import Column, String, Float, Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class TxnType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TxnSource(str, enum.Enum):
    COUNTER = "COUNTER"
    RIDER = "RIDER"


class PaymentMode(str, enum.Enum):
    CASH          = "CASH"
    GCASH         = "GCASH"
    MAYA          = "MAYA"
    SHOPEEPAY     = "SHOPEEPAY"
    BANK_TRANSFER = "BANK_TRANSFER"
    CHEQUE        = "CHEQUE"
    OTHER         = "OTHER"


class PaymentStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PENDING  = "PENDING"


class Transaction(Base):
    """
    Every buy/sell transaction recorded at the counter or via rider.
    THAN is computed server-side from daily_avg_cost at time of transaction.
    """
    __tablename__ = "transactions"

    id = Column(String(20), primary_key=True)          # OR-00080412, RD-00000312
    date = Column(Date, nullable=False, index=True)
    time = Column(String(10), nullable=False)
    type = Column(Enum(TxnType), nullable=False)
    source = Column(Enum(TxnSource), nullable=False)
    currency_code = Column(String(10), nullable=False, index=True)
    foreign_amt = Column(Float, nullable=False)
    rate = Column(Float, nullable=False)
    php_amt = Column(Float, nullable=False)             # foreign_amt × rate
    daily_avg_cost = Column(Float, nullable=False)      # snapshot at time of txn
    than = Column(Float, default=0)                     # (rate − avg) × qty, 0 for buys
    cashier = Column(String(50), nullable=False)
    customer = Column(String(100), nullable=True)
    payment_mode   = Column(Enum(PaymentMode), default=PaymentMode.CASH, nullable=False)
    bank_id        = Column(Integer, ForeignKey("banks.id"), nullable=True)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.RECEIVED, nullable=False)
    confirmed_by   = Column(String(50), nullable=True)   # admin who confirmed pending payment
    confirmed_at   = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class DispatchStatus(str, enum.Enum):
    IN_FIELD = "IN_FIELD"
    RETURNED = "RETURNED"
    OFF      = "OFF"


class RiderDispatch(Base):
    """
    Tracks riders dispatched with starting PHP cash.
    One row per rider per dispatch (a rider may be dispatched multiple times a day).
    """
    __tablename__ = "rider_dispatches"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date          = Column(Date, nullable=False, index=True)
    rider_username= Column(String(50), nullable=False, index=True)
    rider_name    = Column(String(100), nullable=False)
    status        = Column(Enum(DispatchStatus), default=DispatchStatus.IN_FIELD, nullable=False)
    dispatch_time = Column(String(10), nullable=True)
    return_time   = Column(String(10), nullable=True)
    cash_php      = Column(Float, default=0)
    remit_php     = Column(Float, nullable=True)
    notes         = Column(String(200), nullable=True)
    dispatched_by = Column(String(50), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())


class RiderDispatchItem(Base):
    """Currency items given to a rider on dispatch."""
    __tablename__ = "rider_dispatch_items"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_id = Column(UUID(as_uuid=True), ForeignKey("rider_dispatches.id", ondelete="CASCADE"), nullable=False)
    currency    = Column(String(10), nullable=False)
    amount      = Column(Float, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class RiderRemitItem(Base):
    """Currency items returned by a rider on remit."""
    __tablename__ = "rider_remit_items"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_id = Column(UUID(as_uuid=True), ForeignKey("rider_dispatches.id", ondelete="CASCADE"), nullable=False)
    currency    = Column(String(10), nullable=False)
    amount      = Column(Float, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class RiderBorrow(Base):
    """
    Cash borrowed by a rider from a branch or another rider while in the field.
    Must be returned and reconciled.
    """
    __tablename__ = "rider_borrows"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_id = Column(UUID(as_uuid=True), ForeignKey("rider_dispatches.id"), nullable=False)
    source_type = Column(String(10), nullable=False)   # BRANCH | RIDER
    source_name = Column(String(100), nullable=False)  # branch name or rider username
    amount_php  = Column(Float, nullable=False)
    is_returned = Column(String(1), default="N")       # Y / N
    notes       = Column(String(200), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class DailySummary(Base):
    """
    EOD snapshot — one row per business day.
    Replaces the manual CASHIER + BREAKDOWN sheets.
    """
    __tablename__ = "daily_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, unique=True, index=True)
    opening_capital = Column(Float, nullable=False)
    php_cash = Column(Float, default=0)
    total_stock_value = Column(Float, default=0)
    total_capital = Column(Float, default=0)
    total_than = Column(Float, default=0)
    total_bought = Column(Float, default=0)
    total_sold = Column(Float, default=0)
    closed_by = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
