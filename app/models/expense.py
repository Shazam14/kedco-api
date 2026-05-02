from sqlalchemy import Column, String, Float, Date, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class ExpenseStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


EXPENSE_CATEGORIES = [
    "OFFICE_SUPPLIES",
    "UTILITIES",
    "TRANSPORTATION",
    "MEALS",
    "MAINTENANCE",
    "SALARY_ADVANCE",
    "BANK_CHARGES",
    "COMMISSION_PAYOUT",
    "OTHERS",
]


class Expense(Base):
    __tablename__ = "expenses"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    date        = Column(Date, nullable=False, index=True)
    amount_php  = Column(Float, nullable=False)
    category    = Column(String(30), nullable=False)
    description = Column(String(200), nullable=True)
    referrer    = Column(String(100), nullable=True)
    recorded_by = Column(String(50), nullable=False)
    # Stamped at create time so cashier views can scope to the current OPEN shift.
    shift_id    = Column(UUID(as_uuid=True), ForeignKey("teller_shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    status      = Column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING, nullable=False)
    approved_by = Column(String(50), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
