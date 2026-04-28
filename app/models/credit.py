from sqlalchemy import Column, String, Float, Date, DateTime, Integer, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class CreditType(str, enum.Enum):
    UPFRONT     = "UPFRONT"      # interest kept at disbursement; 1 installment = principal payback
    INSTALLMENT = "INSTALLMENT"  # (principal + interest) ÷ N payments, Ken sets each due date


class CreditStatus(str, enum.Enum):
    ACTIVE    = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecialCredit(Base):
    """
    A credit extended to a 'special' (read: difficult but accommodated) customer.
    Two modes:
      UPFRONT     — interest collected at disbursement; track repayment of principal only.
      INSTALLMENT — principal + interest split across N payments on dates Ken sets.
    """
    __tablename__ = "special_credits"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_name = Column(String(100), nullable=False)
    currency_code = Column(String(10),  nullable=False)          # PHP, USD, etc.
    principal     = Column(Float, nullable=False)                # loan amount
    interest      = Column(Float, nullable=False)                # interest charged
    credit_type   = Column(Enum(CreditType), nullable=False)
    status        = Column(Enum(CreditStatus), default=CreditStatus.ACTIVE, nullable=False)
    disbursed_date= Column(Date, nullable=False)                 # date money was given out
    notes         = Column(String(300), nullable=True)
    created_by    = Column(String(50), nullable=False)           # admin username
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())


class CreditDraw(Base):
    """
    An additional draw (top-up borrow) against an active SpecialCredit.
    Customers may draw again after the configured cooldown period.
    """
    __tablename__ = "credit_draws"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_id  = Column(UUID(as_uuid=True), ForeignKey("special_credits.id"), nullable=False, index=True)
    amount     = Column(Float, nullable=False)
    notes      = Column(String(300), nullable=True)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """
    Key/value store for admin-configurable application settings.
    """
    __tablename__ = "app_settings"

    key        = Column(String(100), primary_key=True)
    value      = Column(Text, nullable=False)
    updated_by = Column(String(50), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CreditInstallment(Base):
    """
    One payment slot per credit.
    UPFRONT  → 1 row, amount = principal (interest already taken), due_date = Ken picks.
    INSTALLMENT → N rows, amount = (principal + interest) / N, due_date = Ken picks each.
    """
    __tablename__ = "credit_installments"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_id      = Column(UUID(as_uuid=True), ForeignKey("special_credits.id"), nullable=False, index=True)
    installment_no = Column(Integer, nullable=False)   # 1, 2, 3 …
    due_date       = Column(Date, nullable=True)        # optional — repayment date not enforced
    amount         = Column(Float, nullable=False)      # amount expected for this slot
    paid_at        = Column(Date, nullable=True)        # null = not yet paid
    received_by    = Column(String(50), nullable=True)  # admin who recorded the payment
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
