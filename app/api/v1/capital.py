from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.core.today import get_today
from app.models.capital import PhpCapitalEntry, BranchCapital, PesoKenEntry, MiscEntry
from app.models.currency import Currency, DailyPosition, DailyRate
from app.models.investor import Investor
from app.models.shift import TellerShift, ShiftStatus
from app.models.transaction import Transaction, TxnPayment, TxnType, PaymentMode, PaymentStatus
from app.models.user import User
from app.api.v1.auth import require_role, TokenData
from app.api.v1.shifts import _treasurer_aggregates
from app.services.shifts import compute_expected_cash_treasurer

router = APIRouter(prefix="/capital", tags=["capital"])

# Real treasurers per Ken (project_db_users.md). supervisor1/supervisor2 are
# test accounts and excluded from reconciliation.
TREASURER_USERNAMES = ("treasurer1", "treasurer2")


class CapitalEntryIn(BaseModel):
    amount_php: float                    # signed: + injection, - withdrawal
    note:       Optional[str] = None
    entry_date: Optional[date_type] = None  # defaults to today (PHT)


class CapitalEntryOut(BaseModel):
    id:         str
    amount_php: float
    note:       Optional[str]
    entry_date: date_type
    created_by: str
    created_at: datetime


class CapitalLedgerOut(BaseModel):
    running_total: float
    entries:       list[CapitalEntryOut]


def _to_out(e: PhpCapitalEntry) -> CapitalEntryOut:
    return CapitalEntryOut(
        id=str(e.id),
        amount_php=e.amount_php,
        note=e.note,
        entry_date=e.entry_date,
        created_by=e.created_by,
        created_at=e.created_at,
    )


@router.get("/php", response_model=CapitalLedgerOut)
async def get_php_capital(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(PhpCapitalEntry)
        .order_by(PhpCapitalEntry.entry_date.desc(), PhpCapitalEntry.created_at.desc())
        .all()
    )
    running_total = round(sum(e.amount_php for e in entries), 2)
    return CapitalLedgerOut(
        running_total=running_total,
        entries=[_to_out(e) for e in entries],
    )


@router.post("/php", response_model=CapitalEntryOut, status_code=status.HTTP_201_CREATED)
async def add_php_capital_entry(
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")

    entry = PhpCapitalEntry(
        amount_php=payload.amount_php,
        note=payload.note,
        entry_date=payload.entry_date or get_today(),
        created_by=current_user.username,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


def _parse_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="Entry not found.")


@router.patch("/php/{entry_id}", response_model=CapitalEntryOut)
async def update_php_capital_entry(
    entry_id: str,
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")
    entry = db.query(PhpCapitalEntry).filter(PhpCapitalEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    entry.amount_php = payload.amount_php
    entry.note       = payload.note
    if payload.entry_date is not None:
        entry.entry_date = payload.entry_date
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


@router.delete("/php/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_php_capital_entry(
    entry_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entry = db.query(PhpCapitalEntry).filter(PhpCapitalEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    db.delete(entry)
    db.commit()


# ── Reconciliation components ─────────────────────────────────────────
# Ken's formula: Capital − Stocks − Payables − Branches − Merly − Ken = Available
# Each component below is a building block; the full /reconciliation endpoint
# composes them. See project_peso_capital_model.md for the full plan.


class StockLine(BaseModel):
    code:           str
    closing_qty:    float
    closing_rate:   float        # next-day carry-in rate (= today's closing rate)
    closing_php:    float


class StocksOut(BaseModel):
    date:        date_type
    total_php:   float
    lines:       list[StockLine]


@router.get("/stocks", response_model=StocksOut)
async def get_stocks(
    target_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Stocks = Σ(closing_qty × next-day carry_in_rate) per currency for `date`.
    Closing qty = today's carry_in_qty + buys − sells (per Ken: 'stocks left').
    Rate = next-day carry_in_rate (matches EOD report's stock_summary).
    """
    target = target_date or get_today()
    next_day = target + timedelta(days=1)

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()

    # Opening qty per ccy (today's carry-in)
    opening = {
        p.currency_code: p.carry_in_qty
        for p in db.query(DailyPosition).filter(DailyPosition.date == target).all()
    }
    # Closing rate per ccy (next-day's carry-in = today's closing).
    # Pre-EOD fallback: today's daily_rates.sell_rate (becomes tomorrow's
    # carry-in after EOD), so reconciliation works before EOD close.
    closing_rate = {
        p.currency_code: p.carry_in_rate
        for p in db.query(DailyPosition).filter(DailyPosition.date == next_day).all()
    }
    if not closing_rate:
        closing_rate = {
            r.currency_code: r.sell_rate
            for r in db.query(DailyRate).filter(DailyRate.date == target).all()
        }

    txns = (
        db.query(Transaction)
        .filter(Transaction.date == target)
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )
    delta_qty: dict[str, float] = {}
    for t in txns:
        if t.type == TxnType.BUY:
            delta_qty[t.currency_code] = delta_qty.get(t.currency_code, 0.0) + t.foreign_amt
        elif t.type == TxnType.SELL:
            delta_qty[t.currency_code] = delta_qty.get(t.currency_code, 0.0) - t.foreign_amt
        elif t.type == TxnType.EXCESS:
            delta_qty[t.currency_code] = delta_qty.get(t.currency_code, 0.0) + t.foreign_amt

    all_codes = set(opening) | set(delta_qty)
    lines: list[StockLine] = []
    total_php = 0.0
    for code in sorted(all_codes):
        closing_qty = opening.get(code, 0.0) + delta_qty.get(code, 0.0)
        rate = closing_rate.get(code, 0.0)
        php = round(closing_qty * rate, 2)
        total_php += php
        lines.append(StockLine(
            code=code, closing_qty=closing_qty,
            closing_rate=rate, closing_php=php,
        ))

    return StocksOut(date=target, total_php=round(total_php, 2), lines=lines)


class PayableLine(BaseModel):
    txn_id:     str
    txn_date:   date_type
    customer:   Optional[str]
    method:     str
    amount_php: float


class PayablesOut(BaseModel):
    date:       date_type   # outstanding *as of* this date
    total_php:  float
    lines:      list[PayableLine]


@router.get("/payables", response_model=PayablesOut)
async def get_payables(
    target_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Payables = customer payments by CHEQUE or BANK_TRANSFER that are not yet
    cleared as cash, summed across all txns up to `date`. Per Ken: 'PAYABLES
    YUNG MGA CUSTOMER BAYAD CHEKE OR BANK TX'.
    """
    target = target_date or get_today()

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()

    rows = (
        db.query(TxnPayment, Transaction)
        .join(Transaction, TxnPayment.txn_id == Transaction.id)
        .filter(Transaction.date <= target)
        .filter(~Transaction.cashier.in_(demo_users))
        .filter(TxnPayment.method.in_([PaymentMode.CHEQUE, PaymentMode.BANK_TRANSFER]))
        .filter(TxnPayment.status == PaymentStatus.PENDING)
        .order_by(Transaction.date.desc(), TxnPayment.created_at.desc())
        .all()
    )

    lines = [
        PayableLine(
            txn_id=t.id, txn_date=t.date, customer=t.customer,
            method=p.method.value, amount_php=round(p.amount_php, 2),
        )
        for p, t in rows
    ]
    total_php = round(sum(line.amount_php for line in lines), 2)
    return PayablesOut(date=target, total_php=total_php, lines=lines)


# ── Branches Capital (per-branch peso allocation, admin-config) ───────


class BranchCapitalRow(BaseModel):
    branch_code: str
    amount_php:  float
    updated_by:  Optional[str]
    updated_at:  Optional[datetime]


class BranchCapitalOut(BaseModel):
    total_php: float
    rows:      list[BranchCapitalRow]


class BranchCapitalIn(BaseModel):
    amount_php: float


@router.get("/branches", response_model=BranchCapitalOut)
async def list_branch_capital(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    rows = db.query(BranchCapital).order_by(BranchCapital.branch_code).all()
    out_rows = [
        BranchCapitalRow(
            branch_code=r.branch_code, amount_php=r.amount_php,
            updated_by=r.updated_by, updated_at=r.updated_at,
        )
        for r in rows
    ]
    total = round(sum(r.amount_php for r in rows), 2)
    return BranchCapitalOut(total_php=total, rows=out_rows)


@router.put("/branches/{branch_code}", response_model=BranchCapitalRow)
async def upsert_branch_capital(
    branch_code: str,
    payload:     BranchCapitalIn,
    current_user: TokenData = Depends(require_role("admin")),
    db:          Session = Depends(get_db),
):
    row = db.query(BranchCapital).filter(BranchCapital.branch_code == branch_code).first()
    if row is None:
        row = BranchCapital(
            branch_code=branch_code, amount_php=payload.amount_php,
            updated_by=current_user.username,
        )
        db.add(row)
    else:
        row.amount_php = payload.amount_php
        row.updated_by = current_user.username
    db.commit()
    db.refresh(row)
    return BranchCapitalRow(
        branch_code=row.branch_code, amount_php=row.amount_php,
        updated_by=row.updated_by, updated_at=row.updated_at,
    )


@router.delete("/branches/{branch_code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch_capital(
    branch_code: str,
    current_user: TokenData = Depends(require_role("admin")),
    db:          Session = Depends(get_db),
):
    row = db.query(BranchCapital).filter(BranchCapital.branch_code == branch_code).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Branch capital row not found.")
    db.delete(row)
    db.commit()


# ── Peso Ken (Ken's personal float, signed ledger) ────────────────────


def _peso_ken_to_out(e: PesoKenEntry) -> CapitalEntryOut:
    return CapitalEntryOut(
        id=str(e.id), amount_php=e.amount_php, note=e.note,
        entry_date=e.entry_date, created_by=e.created_by, created_at=e.created_at,
    )


@router.get("/peso-ken", response_model=CapitalLedgerOut)
async def get_peso_ken(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(PesoKenEntry)
        .order_by(PesoKenEntry.entry_date.desc(), PesoKenEntry.created_at.desc())
        .all()
    )
    running_total = round(sum(e.amount_php for e in entries), 2)
    return CapitalLedgerOut(
        running_total=running_total,
        entries=[_peso_ken_to_out(e) for e in entries],
    )


@router.post("/peso-ken", response_model=CapitalEntryOut, status_code=status.HTTP_201_CREATED)
async def add_peso_ken_entry(
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")
    entry = PesoKenEntry(
        amount_php=payload.amount_php,
        note=payload.note,
        entry_date=payload.entry_date or get_today(),
        created_by=current_user.username,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _peso_ken_to_out(entry)


@router.patch("/peso-ken/{entry_id}", response_model=CapitalEntryOut)
async def update_peso_ken_entry(
    entry_id: str,
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")
    entry = db.query(PesoKenEntry).filter(PesoKenEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    entry.amount_php = payload.amount_php
    entry.note       = payload.note
    if payload.entry_date is not None:
        entry.entry_date = payload.entry_date
    db.commit()
    db.refresh(entry)
    return _peso_ken_to_out(entry)


@router.delete("/peso-ken/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peso_ken_entry(
    entry_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entry = db.query(PesoKenEntry).filter(PesoKenEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    db.delete(entry)
    db.commit()


# ── Misc (catch-all peso pool, signed ledger) ───────────────────────


def _misc_to_out(e: MiscEntry) -> CapitalEntryOut:
    return CapitalEntryOut(
        id=str(e.id), amount_php=e.amount_php, note=e.note,
        entry_date=e.entry_date, created_by=e.created_by, created_at=e.created_at,
    )


@router.get("/misc", response_model=CapitalLedgerOut)
async def get_misc(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(MiscEntry)
        .order_by(MiscEntry.entry_date.desc(), MiscEntry.created_at.desc())
        .all()
    )
    running_total = round(sum(e.amount_php for e in entries), 2)
    return CapitalLedgerOut(
        running_total=running_total,
        entries=[_misc_to_out(e) for e in entries],
    )


@router.post("/misc", response_model=CapitalEntryOut, status_code=status.HTTP_201_CREATED)
async def add_misc_entry(
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")
    entry = MiscEntry(
        amount_php=payload.amount_php,
        note=payload.note,
        entry_date=payload.entry_date or get_today(),
        created_by=current_user.username,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _misc_to_out(entry)


@router.patch("/misc/{entry_id}", response_model=CapitalEntryOut)
async def update_misc_entry(
    entry_id: str,
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")
    entry = db.query(MiscEntry).filter(MiscEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    entry.amount_php = payload.amount_php
    entry.note       = payload.note
    if payload.entry_date is not None:
        entry.entry_date = payload.entry_date
    db.commit()
    db.refresh(entry)
    return _misc_to_out(entry)


@router.delete("/misc/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_misc_entry(
    entry_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entry = db.query(MiscEntry).filter(MiscEntry.id == _parse_uuid(entry_id)).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    db.delete(entry)
    db.commit()


# ── Peso Merly (treasurer1 + treasurer2 expected cash for date) ──────


class TreasurerLine(BaseModel):
    username:          str
    full_name:         Optional[str]
    shift_status:      Optional[str]      # OPEN / CLOSED / None (no shift today)
    expected_cash_php: float


class PesoMerlyOut(BaseModel):
    date:       date_type
    total_php:  float
    lines:      list[TreasurerLine]


@router.get("/peso-merly", response_model=PesoMerlyOut)
async def get_peso_merly(
    target_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Peso Merly = sum of treasurer1 + treasurer2 expected cash on `date`.
    Mirrors supervisor screen formula (compute_expected_cash_treasurer) so OPEN
    shifts get live numbers and CLOSED shifts use the same path.
    """
    target = target_date or get_today()

    lines: list[TreasurerLine] = []
    total = 0.0
    for username in TREASURER_USERNAMES:
        user = db.query(User).filter(User.username == username).first()
        # Most recent shift on target date (treasurer typically opens one per day).
        shift = (
            db.query(TellerShift)
            .filter(TellerShift.cashier == username)
            .filter(TellerShift.date == target)
            .order_by(TellerShift.opened_at.desc())
            .first()
        )

        expected = 0.0
        shift_status: Optional[str] = None
        if shift is not None:
            shift_status = shift.status.value
            agg = _treasurer_aggregates(shift, db)
            if agg is not None:
                expected = compute_expected_cash_treasurer(
                    shift.opening_cash_php,
                    agg["from_dispatches_php"],
                    agg["dispatches_out_php"],
                    agg["from_cashier_php"],
                    agg["bale_peso_php"],
                    agg["vault_returns_php"],
                )

        lines.append(TreasurerLine(
            username=username,
            full_name=user.full_name if user else None,
            shift_status=shift_status,
            expected_cash_php=round(expected, 2),
        ))
        total += expected

    return PesoMerlyOut(date=target, total_php=round(total, 2), lines=lines)


# ── Reconciliation (composes all 6 components) ───────────────────────


class ReconciliationOut(BaseModel):
    date:           date_type
    capital_php:    float    # total owner principal injected
    stocks_php:     float    # FCY inventory at next-day carry-in rate
    payables_php:   float    # CHEQUE/BANK pending payments
    branches_php:   float    # admin-set per-branch allocation
    peso_ken_php:   float    # Ken's personal float ledger total
    misc_php:       float    # catch-all peso pool ledger total
    peso_merly_php: float    # treasurer1 + treasurer2 expected drawer cash
    available_php:  float    # capital - stocks - payables - branches - peso_ken - misc - peso_merly
    investor_php:   float    # separate line: pending peso for investor


@router.get("/reconciliation", response_model=ReconciliationOut)
async def get_reconciliation(
    target_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Ken's formula:
      Available = Capital − Stocks − Payables − Branches − Peso Ken − Misc − Peso Merly
    Investor is shown as a separate line, not subtracted.
    """
    target = target_date or get_today()

    capital = (await get_php_capital(current_user, db)).running_total
    stocks   = (await get_stocks(target, current_user, db)).total_php
    payables = (await get_payables(target, current_user, db)).total_php
    branches = (await list_branch_capital(current_user, db)).total_php
    peso_ken = (await get_peso_ken(current_user, db)).running_total
    misc       = (await get_misc(current_user, db)).running_total
    peso_merly = (await get_peso_merly(target, current_user, db)).total_php
    investor = round(sum(i.capital_php for i in db.query(Investor).all()), 2)

    available = round(capital - stocks - payables - branches - peso_ken - misc - peso_merly, 2)

    return ReconciliationOut(
        date=target,
        capital_php=capital,
        stocks_php=stocks,
        payables_php=payables,
        branches_php=branches,
        peso_ken_php=peso_ken,
        misc_php=misc,
        peso_merly_php=peso_merly,
        available_php=available,
        investor_php=investor,
    )
