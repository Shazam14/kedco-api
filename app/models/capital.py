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
    entry_date    = Column(Date, nullable=False, index=True) # business date the capital event applies to
    created_by    = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
