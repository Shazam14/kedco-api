from sqlalchemy import Column, String, Float, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PhpCapitalEntry(Base):
    """
    Owner-contributed PHP principal — the capital that funds the business.

    Distinct from safe_movements (operational vault flow) and from bale (treasurer-side
    movement). A positive amount is capital injected; a negative amount is capital
    withdrawn. The running sum across all entries is the current Capital PHP balance.
    """
    __tablename__ = "php_capital_entries"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount_php    = Column(Float, nullable=False)            # signed: + injection, - withdrawal
    note          = Column(String(300), nullable=True)
    entry_date    = Column(Date, nullable=False, index=True)
    created_by    = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class BranchCapital(Base):
    """
    Per-branch peso allocation set by admin (Ken's "Branches Capital" line in
    the reconciliation formula). One row per branch_code; admin-editable via
    /capital/branches. Used as a subtraction in Available Peso Capital.
    """
    __tablename__ = "branch_capital"

    branch_code = Column(String(20), primary_key=True)
    amount_php  = Column(Float, nullable=False, default=0)
    updated_by  = Column(String(50), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())


class PesoKenEntry(Base):
    """
    Ken's personal peso float (~₱300k–₱500k) — the pool he draws from to pay
    THAN. Mirror of PhpCapitalEntry but a separate physical pool, so it must
    not be summed into owner principal. Signed amounts: + add, − withdraw.
    """
    __tablename__ = "peso_ken_entries"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount_php    = Column(Float, nullable=False)            # signed
    note          = Column(String(300), nullable=True)
    entry_date    = Column(Date, nullable=False, index=True)
    created_by    = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
