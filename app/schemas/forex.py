from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import date, datetime


class CurrencyRateIn(BaseModel):
    code: str
    sell_rate: float
    buy_rate: float


class TransactionIn(BaseModel):
    type: Literal["BUY", "SELL"]
    source: Literal["COUNTER", "RIDER"]
    currency: str
    foreign_amt: float
    rate: float
    cashier: str
    customer: Optional[str] = None
    payment_mode: Optional[str] = "CASH"
    bank_id: Optional[int] = None
    official_rate: Optional[float] = None  # guide rate the cashier was given
    referrer: Optional[str] = None
    payment_tag: Optional[str] = None    # ADVANCE | LATE
    reference_date: Optional[date] = None


class TransactionOut(BaseModel):
    id: str
    time: str
    type: str
    source: str
    currency: str
    foreign_amt: float
    rate: float
    php_amt: float
    than: float
    cashier: str
    customer: Optional[str] = None
    payment_mode: str = "CASH"
    bank_id: Optional[int] = None
    official_rate: Optional[float] = None
    referrer: Optional[str] = None
    payment_tag: Optional[str] = None
    reference_date: Optional[date] = None


class CurrencyPositionOut(BaseModel):
    code: str
    name: str
    flag: str
    category: str
    decimal_places: int
    total_qty: float
    daily_avg_cost: float
    today_buy_rate: float
    today_sell_rate: float
    stock_value_php: float
    today_gain_per_unit: float
    unrealized_php: float


class TransactionPatch(BaseModel):
    customer:       Optional[str]   = None
    payment_mode:   Optional[str]   = None
    bank_id:        Optional[int]   = None
    rate:           Optional[float] = None
    foreign_amt:    Optional[float] = None
    official_rate:  Optional[float] = None
    referrer:       Optional[str]   = None
    payment_tag:    Optional[str]   = None
    reference_date: Optional[date]  = None


class DashboardSummaryOut(BaseModel):
    date: date
    opening_capital: float
    php_cash: float
    total_stock_value: float
    total_capital: float
    total_unrealized: float
    total_than_today: float
    total_bought_today: float
    total_sold_today: float
    positions: List[CurrencyPositionOut]
    recent_transactions: List[TransactionOut]
