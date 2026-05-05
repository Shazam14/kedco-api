from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class Investor(Base):
    """
    Investor master data — capital contributors who get a monthly ROI payout.

    The estimator at /admin/investor-share computes per-investor monthly payout
    as capital_php * monthly_rate_pct / 100. Payments themselves are settled
    off-system (typically by extracting equivalent FX stock).
    """
    __tablename__ = "investors"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name             = Column(String(100), nullable=False)
    capital_php      = Column(Float, nullable=False)
    monthly_rate_pct = Column(Float, nullable=False)
    note             = Column(String(300), nullable=True)
    created_by       = Column(String(50), nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
