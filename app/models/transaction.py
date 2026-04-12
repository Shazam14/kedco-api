from sqlalchemy import Column, String, Float, Date, DateTime, Enum, ForeignKey
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RiderDispatch(Base):
    """
    Tracks riders dispatched with cash and foreign currency stock.
    """
    __tablename__ = "rider_dispatches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, index=True)
    rider_name = Column(String(100), nullable=False)
    status = Column(String(20), default="IN_FIELD")    # IN_FIELD, RETURNED, OFF
    dispatch_time = Column(String(10), nullable=True)
    cash_php = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
