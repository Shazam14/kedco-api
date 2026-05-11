from sqlalchemy import Column, String, Float, Date, DateTime, Boolean, ForeignKey
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


class ValeParty(Base):
    """
    External party who lends or receives cash via VALE (informal IOU). Each
    party gets its own running balance from the sum of signed vale_entries.
    + entries = cash they sent us; − entries = cash we returned to them.

    investor_id is a soft link to `investors`: when populated, this party is
    also an investor — Ken's total exposure to them is capital + outstanding
    vale. Nullable because not every vale party is an investor.
    """
    __tablename__ = "vale_parties"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(80), nullable=False, unique=True, index=True)
    note        = Column(String(300), nullable=True)
    investor_id = Column(UUID(as_uuid=True), ForeignKey("investors.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active   = Column(Boolean, nullable=False, server_default="true")
    created_by  = Column(String(50), nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class ValeEntry(Base):
    """
    Signed ledger of a VALE party's running balance. Paired with either a
    CashReplenishment(source='VALE', +amount) when cash comes INTO the
    drawer from the party, or an InterBranchOutflow(destination='VALE',
    -amount) when cash is returned TO the party. Mirrors PesoKenEntry.
    """
    __tablename__ = "vale_entries"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    party_id   = Column(UUID(as_uuid=True), ForeignKey("vale_parties.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount_php = Column(Float, nullable=False)                # signed
    note       = Column(String(300), nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MiscEntry(Base):
    """
    Miscellaneous peso pool — catch-all for cash held outside the main pools
    (PHP Capital, Peso Ken, Branches, Treasurer). Subtracts from Available in
    the reconciliation formula. Signed: + add, − withdraw.
    """
    __tablename__ = "misc_entries"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount_php    = Column(Float, nullable=False)            # signed
    note          = Column(String(300), nullable=True)
    entry_date    = Column(Date, nullable=False, index=True)
    created_by    = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
