from sqlalchemy import Column, String, Integer, Boolean
from app.core.database import Base


class Bank(Base):
    """Banks and e-wallets used for payment tagging on rider transactions."""
    __tablename__ = "banks"

    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False, unique=True)   # BDO, BPI, GCASH …
    is_active   = Column(Boolean, default=True, nullable=False)
    sort_order  = Column(Integer, default=99)
