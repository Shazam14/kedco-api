from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date, datetime

from app.core.database import get_db
from app.models.shift import TellerShift, ShiftStatus
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.shift import ShiftOpenIn, ShiftCloseIn, ShiftOut
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _shift_to_out(shift: TellerShift, db: Session) -> ShiftOut:
    """Convert a TellerShift row to ShiftOut, computing transaction summary."""
    txns = db.query(Transaction).filter_by(
        date=shift.date,
        cashier=shift.cashier,
    ).all()

    total_sold   = sum(t.php_amt for t in txns if t.type == "SELL")
    total_bought = sum(t.php_amt for t in txns if t.type == "BUY")
    total_than   = sum(t.than for t in txns)

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
        txn_count=len(txns),
        total_sold_php=round(total_sold, 2),
        total_bought_php=round(total_bought, 2),
        total_than=round(total_than, 2),
    )


@router.post("/open", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(
    body: ShiftOpenIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = date.today()

    # Block if cashier already has an open shift today
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
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/close", response_model=ShiftOut)
async def close_shift(
    body: ShiftCloseIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = date.today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No open shift found for today.",
        )

    # Compute expected cash:
    # opening_cash + PHP received from SELLs - PHP paid out for BUYs
    txns = db.query(Transaction).filter_by(
        date=today,
        cashier=current_user.username,
    ).all()
    total_sold   = sum(t.php_amt for t in txns if t.type == "SELL")
    total_bought = sum(t.php_amt for t in txns if t.type == "BUY")
    expected = round(shift.opening_cash_php + total_sold - total_bought, 2)
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
    today = date.today()
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
    shifts = db.query(TellerShift).filter_by(date=date.today()).order_by(
        TellerShift.opened_at
    ).all()
    return [_shift_to_out(s, db) for s in shifts]
