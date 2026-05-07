from sqlalchemy import Column, String, Float, Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class TxnType(str, enum.Enum):
    BUY    = "BUY"
    SELL   = "SELL"
    EXCESS = "EXCESS"  # foreign currency received with no PHP paid (windfall/overage)


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
    official_rate  = Column(Float, nullable=True)         # admin-set rate at time of txn
    referrer       = Column(String(100), nullable=True)   # tour guide / referral source
    payment_tag    = Column(String(10), nullable=True)    # ADVANCE | LATE | null
    reference_date = Column(Date, nullable=True)          # date the payment relates to
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.RECEIVED, nullable=False)
    confirmed_by   = Column(String(50), nullable=True)   # admin who confirmed pending payment
    confirmed_at   = Column(DateTime(timezone=True), nullable=True)
    batch_id       = Column(UUID(as_uuid=True), nullable=True, index=True)
    note           = Column(String(300), nullable=True)      # free-text note, used for EXCESS entries
    terminal_id    = Column(String(50), nullable=True)        # device label e.g. "Counter 1", "Phone"
    branch_id      = Column(String(20), nullable=True)        # branch code e.g. "MAIN", "CTS"
    customer_id    = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    payments = relationship(
        "TxnPayment",
        back_populates="transaction",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TxnPayment(Base):
    """
    One slice of a transaction's payment. A transaction may be paid via several
    methods (e.g. ₱200k cash + ₱800k GCash) — each slice carries its own status,
    so PENDING/RECEIVED is per-slice, not per-txn. SUM(amount_php) per txn must
    equal transactions.php_amt (enforced in app layer, not DB).
    """
    __tablename__ = "txn_payments"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    txn_id       = Column(String(20), ForeignKey("transactions.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    method       = Column(Enum(PaymentMode), nullable=False)
    amount_php   = Column(Float, nullable=False)
    status       = Column(Enum(PaymentStatus), default=PaymentStatus.RECEIVED, nullable=False, index=True)
    reference_no = Column(String(60), nullable=True)
    received_at  = Column(DateTime(timezone=True), nullable=True)
    confirmed_by = Column(String(50), nullable=True)
    # Cheque-only: set when the treasurer confirms the bank cleared the cheque.
    # Null while in flight; only cleared cheques count toward drawer cash.
    cleared_at   = Column(DateTime(timezone=True), nullable=True, index=True)
    cleared_by   = Column(String(50), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    transaction  = relationship("Transaction", back_populates="payments")


class DispatchStatus(str, enum.Enum):
    IN_FIELD = "IN_FIELD"
    REMITTED = "REMITTED"
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


class RiderDispatchTopup(Base):
    """Additional PHP cash issued to a dispatched rider during the day. Audit log of mid-shift top-ups."""
    __tablename__ = "rider_dispatch_topups"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_id   = Column(UUID(as_uuid=True), ForeignKey("rider_dispatches.id", ondelete="CASCADE"), nullable=False)
    amount_php    = Column(Float, nullable=False)
    time          = Column(String(10), nullable=True)
    dispatched_by = Column(String(50), nullable=True)
    notes         = Column(String(200), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


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
