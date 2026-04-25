from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, date

from app.core.database import get_db
from app.models.shift import TellerShift, ShiftStatus, CashReplenishment
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.shift import ShiftOpenIn, ShiftCloseIn, ReplenishIn, ShiftOut, ReplenishmentOut
from app.api.v1.auth import require_role, TokenData
from app.core.today import get_today

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

    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL")
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY")
    total_than       = sum(t.than for t in txns)
    total_commission = sum(_comm(t) for t in txns)
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

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
        replenishments=[
            ReplenishmentOut(id=str(r.id), amount_php=r.amount_php, note=r.note, added_at=r.added_at)
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

    replenishment = CashReplenishment(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
    )
    db.add(replenishment)
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
    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL")
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY")
    total_commission = sum(_comm(t) for t in txns)
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

    expected = round(shift.opening_cash_php + total_sold - total_bought - total_commission + total_replenishment, 2)
    variance = round(body.closing_cash_php - expected, 2)

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
