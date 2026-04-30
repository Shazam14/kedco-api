from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import date, datetime
from uuid import UUID

_Date = date  # alias — prevents Pydantic from resolving 'date' against the field's own default (None)


class CurrencyRateIn(BaseModel):
    code: str
    sell_rate: float
    buy_rate: float


class PaymentSliceIn(BaseModel):
    method: Literal["CASH", "GCASH", "MAYA", "SHOPEEPAY", "BANK_TRANSFER", "CHEQUE", "OTHER"]
    amount_php: float
    status: Optional[Literal["RECEIVED", "PENDING"]] = None
    reference_no: Optional[str] = None


class PaymentSliceOut(BaseModel):
    id: UUID
    method: str
    amount_php: float
    status: str
    reference_no: Optional[str] = None
    received_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None


class TransactionIn(BaseModel):
    type: Literal["BUY", "SELL", "EXCESS"]
    source: Literal["COUNTER", "RIDER"]
    currency: str
    foreign_amt: float
    rate: float                           # 0.0 for EXCESS entries
    cashier: str
    customer: Optional[str] = None
    customer_id: Optional[UUID] = None
    payment_mode: Optional[str] = "CASH"
    bank_id: Optional[int] = None
    official_rate: Optional[float] = None
    referrer: Optional[str] = None
    payment_tag: Optional[str] = None
    payment_status: Optional[Literal["RECEIVED", "PENDING"]] = None
    reference_date: Optional[date] = None
    note: Optional[str] = None            # required for EXCESS, optional otherwise
    terminal_id: Optional[str] = None
    branch_id: Optional[str] = None
    payments: Optional[List[PaymentSliceIn]] = None  # omit = single slice from payment_mode


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
    customer_id: Optional[UUID] = None
    payment_mode: str = "CASH"
    bank_id: Optional[int] = None
    official_rate: Optional[float] = None
    referrer: Optional[str] = None
    payment_tag: Optional[str] = None
    payment_status: str = "RECEIVED"
    reference_date: Optional[date] = None
    batch_id: Optional[UUID] = None
    terminal_id: Optional[str] = None
    branch_id: Optional[str] = None
    date: Optional[_Date] = None
    payments: List[PaymentSliceOut] = []


class BatchItemIn(BaseModel):
    currency: str
    foreign_amt: float
    rate: float
    official_rate: Optional[float] = None


class TransactionBatchIn(BaseModel):
    type: Literal["BUY", "SELL"]
    source: Literal["COUNTER", "RIDER"] = "COUNTER"
    customer: Optional[str] = None
    customer_id: Optional[UUID] = None
    payment_mode: Optional[str] = "CASH"
    bank_id: Optional[int] = None
    referrer: Optional[str] = None
    terminal_id: Optional[str] = None
    branch_id: Optional[str] = None
    items: List[BatchItemIn]


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
    type:           Optional[Literal["BUY", "SELL"]] = None
    customer:       Optional[str]   = None
    customer_id:    Optional[UUID]  = None
    payment_mode:   Optional[str]   = None
    bank_id:        Optional[int]   = None
    rate:           Optional[float] = None
    foreign_amt:    Optional[float] = None
    official_rate:  Optional[float] = None
    referrer:       Optional[str]   = None
    payment_tag:    Optional[str]   = None
    reference_date: Optional[date]  = None


class CapitalTrendPoint(BaseModel):
    date: str
    value: float


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
    capital_trend: List[CapitalTrendPoint]
