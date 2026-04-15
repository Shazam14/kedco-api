from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class ShiftOpenIn(BaseModel):
    opening_cash_php: float
    notes: Optional[str] = None


class ShiftCloseIn(BaseModel):
    closing_cash_php: float
    notes: Optional[str] = None


class ShiftOut(BaseModel):
    id: str
    date: date
    cashier: str
    cashier_name: str
    status: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opening_cash_php: float
    closing_cash_php: Optional[float] = None
    expected_cash_php: Optional[float] = None
    cash_variance: Optional[float] = None
    notes: Optional[str] = None
    # summary fields (populated on close or GET active)
    txn_count: Optional[int] = None
    total_sold_php: Optional[float] = None
    total_bought_php: Optional[float] = None
    total_than: Optional[float] = None
