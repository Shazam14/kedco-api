from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime


class ShiftOpenIn(BaseModel):
    opening_cash_php: float
    notes: Optional[str] = None
    terminal_id: Optional[str] = None
    branch_id: Optional[str] = None


class ShiftCloseIn(BaseModel):
    closing_cash_php: float
    notes: Optional[str] = None


class ReplenishIn(BaseModel):
    amount_php: float
    note: Optional[str] = None
    # Where the cash came from. SAFE writes a paired safe_movement(-amount).
    source: Optional[str] = "TREASURER_FLOAT"


class ReplenishmentOut(BaseModel):
    id: str
    amount_php: float
    note: Optional[str] = None
    source: Optional[str] = "TREASURER_FLOAT"
    added_at: datetime


class InterBranchOutIn(BaseModel):
    amount_php: float
    note: Optional[str] = None


class InterBranchOutflowOut(BaseModel):
    id: str
    amount_php: float
    note: Optional[str] = None
    sent_at: datetime


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
    terminal_id: Optional[str] = None
    branch_id: Optional[str] = None
    # summary fields
    txn_count: Optional[int] = None
    total_sold_php: Optional[float] = None
    total_bought_php: Optional[float] = None
    total_than: Optional[float] = None
    total_commission: Optional[float] = None
    # replenishments
    total_replenishment_php: Optional[float] = None
    # petty cash spent from the till this shift (PENDING + APPROVED expenses)
    total_petty_cash_php: Optional[float] = None
    replenishments: Optional[List[ReplenishmentOut]] = None
    inter_branch_outflows: Optional[List[InterBranchOutflowOut]] = None
    # treasurer-shift aggregates — populated when the shift owner has role=supervisor.
    # Cashier shifts get nulls; UI flips on `is_treasurer_shift`.
    is_treasurer_shift: Optional[bool] = None
    overall_total_bought_php: Optional[float] = None
    overall_total_sold_php: Optional[float] = None
    from_dispatches_php: Optional[float] = None
    dispatches_out_php: Optional[float] = None
    from_cashier_php: Optional[float] = None
    bale_peso_php: Optional[float] = None
    inter_branch_in_php: Optional[float] = None
    inter_branch_out_php: Optional[float] = None
    vault_returns_php: Optional[float] = None
    expenses_php: Optional[float] = None
    cheques_cleared_php: Optional[float] = None
