from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, date

from app.core.database import get_db
from app.models.shift import TellerShift, ShiftStatus, CashReplenishment, SafeMovement
from app.models.transaction import Transaction, PaymentStatus
from app.models.expense import Expense, ExpenseStatus
from app.models.user import User
from app.schemas.shift import ShiftOpenIn, ShiftCloseIn, ReplenishIn, ShiftOut, ReplenishmentOut
from app.api.v1.auth import require_role, TokenData
from app.core.today import get_today
from app.services.shifts import compute_expected_cash, compute_variance

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _comm(t):
    if not t.official_rate:
        return 0.0
    return (t.rate - t.official_rate) * t.foreign_amt if str(t.type) == "SELL" \
        else (t.official_rate - t.rate) * t.foreign_amt


def _shift_to_out(shift: TellerShift, db: Session) -> ShiftOut:
    txns = db.query(Transaction).filter_by(
        date=shift.date,
        cashier=shift.cashier,
    ).all()

    # PENDING transactions excluded from financial totals — cashier hasn't
    # received the PHP yet on a PENDING SELL, hasn't paid yet on a PENDING BUY.
    received = lambda t: t.payment_status != PaymentStatus.PENDING
    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL" and received(t))
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY"  and received(t))
    total_than       = sum(t.than for t in txns if received(t))
    total_commission = sum(_comm(t) for t in txns if received(t))
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

    # PENDING + APPROVED count against the till (cash already left); REJECTED
    # means admin reversed it, so the cashier's drawer should reconcile as if
    # the expense never happened.
    petty_cash_rows = db.query(Expense).filter(
        Expense.recorded_by == shift.cashier,
        Expense.date == shift.date,
        Expense.status != ExpenseStatus.REJECTED,
    ).all()
    total_petty_cash = sum(e.amount_php for e in petty_cash_rows)

    return ShiftOut(
        id=str(shift.id),
        date=shift.date,
        cashier=shift.cashier,
        cashier_name=shift.cashier_name,
        status=shift.status.value,
        opened_at=shift.opened_at,
        closed_at=shift.closed_at,
        opening_cash_php=shift.opening_cash_php,
        closing_cash_php=shift.closing_cash_php,
        expected_cash_php=shift.expected_cash_php,
        cash_variance=shift.cash_variance,
        notes=shift.notes,
        terminal_id=shift.terminal_id,
        branch_id=shift.branch_id,
        txn_count=len(txns),
        total_sold_php=round(total_sold, 2),
        total_bought_php=round(total_bought, 2),
        total_than=round(total_than, 2),
        total_commission=round(total_commission, 2),
        total_replenishment_php=round(total_replenishment, 2),
        total_petty_cash_php=round(total_petty_cash, 2),
        replenishments=[
            ReplenishmentOut(id=str(r.id), amount_php=r.amount_php, note=r.note, source=r.source, added_at=r.added_at)
            for r in shift.replenishments
        ],
    )


@router.post("/open", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(
    body: ShiftOpenIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    existing = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open shift today. Close it before opening a new one.",
        )

    user = db.query(User).filter_by(username=current_user.username).first()
    cashier_name = user.full_name if user else current_user.username

    shift = TellerShift(
        date=today,
        cashier=current_user.username,
        cashier_name=cashier_name,
        status=ShiftStatus.OPEN,
        opening_cash_php=body.opening_cash_php,
        notes=body.notes,
        terminal_id=body.terminal_id or None,
        branch_id=body.branch_id or None,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/replenish", response_model=ShiftOut)
async def replenish_cash(
    body: ReplenishIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    source = (body.source or "TREASURER_FLOAT").upper()
    if source not in {"TREASURER_FLOAT", "SAFE", "EXTERNAL", "OTHER"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid source: {source}")

    replenishment = CashReplenishment(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
        source=source,
    )
    db.add(replenishment)
    db.flush()  # need replenishment.id for the paired safe movement

    if source == "SAFE":
        db.add(SafeMovement(
            amount_php=-abs(body.amount_php),
            reason="REPLENISH_DRAWER",
            note=body.note,
            actor_username=current_user.username,
            related_replenishment_id=replenishment.id,
            movement_date=today,
        ))

    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/close", response_model=ShiftOut)
async def close_shift(
    body: ShiftCloseIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    txns = db.query(Transaction).filter_by(
        date=today,
        cashier=current_user.username,
    ).all()
    # PENDING transactions don't move cash on the cashier side until confirmed.
    received = lambda t: t.payment_status != PaymentStatus.PENDING
    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL" and received(t))
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY"  and received(t))
    total_commission = sum(_comm(t) for t in txns if received(t))
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

    # Petty cash that left the till during this shift's date.
    # PENDING + APPROVED count; REJECTED means admin reversed the expense.
    petty_cash_rows = db.query(Expense).filter(
        Expense.recorded_by == current_user.username,
        Expense.date == today,
        Expense.status != ExpenseStatus.REJECTED,
    ).all()
    total_petty_cash = sum(e.amount_php for e in petty_cash_rows)

    expected = compute_expected_cash(
        shift.opening_cash_php,
        total_sold, total_bought, total_commission, total_replenishment,
        total_petty_cash,
    )
    variance = compute_variance(body.closing_cash_php, expected)

    shift.status            = ShiftStatus.CLOSED
    shift.closed_at         = datetime.now()
    shift.closing_cash_php  = body.closing_cash_php
    shift.expected_cash_php = expected
    shift.cash_variance     = variance
    if body.notes:
        shift.notes = body.notes

    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.get("/active", response_model=ShiftOut)
async def get_active_shift(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active shift.")
    return _shift_to_out(shift, db)


@router.get("/today", response_model=list[ShiftOut])
async def get_today_shifts(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()
    shifts = (
        db.query(TellerShift)
        .filter(TellerShift.date == get_today())
        .filter(~TellerShift.cashier.in_(demo_users))
        .order_by(TellerShift.opened_at)
        .all()
    )
    return [_shift_to_out(s, db) for s in shifts]
