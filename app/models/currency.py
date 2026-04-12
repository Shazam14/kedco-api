from sqlalchemy import Column, String, Float, Date, Integer, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy import DateTime
import uuid
import enum

from app.core.database import Base


class CurrencyCategory(str, enum.Enum):
    MAIN = "MAIN"
    SECOND = "2ND"
    OTHERS = "OTHERS"


class Currency(Base):
    """Master list of currencies handled by the business."""
    __tablename__ = "currencies"

    code = Column(String(10), primary_key=True)  # USD, JPY, EUR
    name = Column(String(100), nullable=False)
    flag = Column(String(10), nullable=True)
    category = Column(Enum(CurrencyCategory), nullable=False)
    decimal_places = Column(Integer, default=4)
    is_active = Column(String(1), default="Y")


class DailyRate(Base):
    """
    Exchange rates set each day by admin.
    One row per currency per day.
    """
    __tablename__ = "daily_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, index=True)
    currency_code = Column(String(10), nullable=False, index=True)
    buy_rate = Column(Float, nullable=False)
    sell_rate = Column(Float, nullable=False)
    set_by = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DailyPosition(Base):
    """
    Opening position per currency per day (carry-in from previous day).
    Qty and rate carried forward at EOD.
    """
    __tablename__ = "daily_positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, index=True)
    currency_code = Column(String(10), nullable=False, index=True)
    carry_in_qty = Column(Float, default=0)
    carry_in_rate = Column(Float, default=0)   # yesterday's closing sell rate
    created_at = Column(DateTime(timezone=True), server_default=func.now())
