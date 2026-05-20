import uuid
from sqlalchemy import Column, String, Float, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class PendingReceivable(Base):
    """
    Standalone ledger of pending receivables (cheques, GCash, PNB transfers).
    Grouped by destination bank inbox (GPO / CBC / MBTC). Lives outside the
    FX txn flow — these are stale receivables tracked in the treasurer's
    notebook, not slices on existing SELL transactions.

    Status:  PENDING (default)  | CLEARED   | BAD_DEBT
    Method:  CHEQUE | GCASH | PNB | TRANSFER | WALKIN | UNKNOWN
    Bank:    GPO    | CBC   | MBTC
    """
    __tablename__ = "pending_receivables"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_name = Column(String(120), nullable=False)
    amount_php    = Column(Float, nullable=False)
    method        = Column(String(20), nullable=False, server_default="UNKNOWN")
    bank_account  = Column(String(20), nullable=False)
    entry_date    = Column(Date, nullable=True, index=True)
    status        = Column(String(20), nullable=False, server_default="PENDING", index=True)
    note          = Column(String(300), nullable=True)
    cleared_at    = Column(DateTime(timezone=True), nullable=True)
    cleared_by    = Column(String(50), nullable=True)
    created_by    = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
