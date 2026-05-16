from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from pydantic import BaseModel
from datetime import date, datetime

from app.core.database import get_db
from app.models.shift import TreasurerFloat, TellerShift, ShiftStatus
from app.models.transaction import Transaction, TxnPayment, PaymentMode
from app.models.user import User
from app.api.v1.auth import require_role, TokenData
from app.core.today import get_today, get_mock_date

router = APIRouter(prefix="/treasurer", tags=["treasurer"])


class FloatIn(BaseModel):
    cashier_username: str
    amount_php: float


class FloatOut(BaseModel):
    id: str
    cashier_username: str
    treasurer_username: str
    amount_php: float
    date: date


class CashierFloatSummary(BaseModel):
    cashier_username: str
    cashier_name: str
    float_amount: float | None
    float_id: str | None


@router.post("/float", response_model=FloatOut)
async def set_cashier_float(
    body: FloatIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    existing = db.query(TreasurerFloat).filter(
        and_(
            TreasurerFloat.cashier_username == body.cashier_username,
            TreasurerFloat.date == today,
        )
    ).first()

    if existing:
        existing.amount_php = body.amount_php
        existing.treasurer_username = current_user.username
        db.commit()
        db.refresh(existing)
        record = existing
    else:
        record = TreasurerFloat(
            cashier_username=body.cashier_username,
            treasurer_username=current_user.username,
            amount_php=body.amount_php,
            date=today,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

    return FloatOut(
        id=str(record.id),
        cashier_username=record.cashier_username,
        treasurer_username=record.treasurer_username,
        amount_php=record.amount_php,
        date=record.date,
    )


@router.get("/cashiers", response_model=list[CashierFloatSummary])
async def list_cashier_floats(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    cashiers = db.query(User).filter(User.role == "cashier").all()
    floats = {
        f.cashier_username: f
        for f in db.query(TreasurerFloat).filter(TreasurerFloat.date == today).all()
    }

    return [
        CashierFloatSummary(
            cashier_username=c.username,
            cashier_name=c.full_name or c.username,
            float_amount=floats[c.username].amount_php if c.username in floats else None,
            float_id=str(floats[c.username].id) if c.username in floats else None,
        )
        for c in cashiers
    ]


@router.get("/pending-float")
async def get_pending_float(
    terminal_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    record = db.query(TreasurerFloat).filter(
        and_(
            TreasurerFloat.cashier_username == current_user.username,
            TreasurerFloat.date == today,
        )
    ).first()

    if record:
        treasurer = db.query(User).filter(User.username == record.treasurer_username).first()
        treasurer_name = (treasurer.full_name or record.treasurer_username) if treasurer else record.treasurer_username
        return {
            "amount_php": record.amount_php,
            "treasurer_username": record.treasurer_username,
            "treasurer_name": treasurer_name,
            "source": "treasurer",
        }

    # Fallback: look for the last closed shift today on the same terminal
    if terminal_id:
        prev = (
            db.query(TellerShift)
            .filter(
                TellerShift.date == today,
                TellerShift.terminal_id == terminal_id,
                TellerShift.status == ShiftStatus.CLOSED,
            )
            .order_by(TellerShift.closed_at.desc())
            .first()
        )
        if prev:
            amount = prev.closing_cash_php if prev.closing_cash_php is not None else prev.expected_cash_php
            if amount is not None:
                return {
                    "amount_php": amount,
                    "source": "handoff",
                    "cashier_name": prev.cashier_name,
                }

    return None


class PendingChequeOut(BaseModel):
    payment_id: str
    txn_id: str
    txn_date: date
    amount_php: float
    reference_no: str | None
    customer: str | None
    cashier: str


@router.get("/cheques/pending", response_model=list[PendingChequeOut])
async def list_pending_cheques(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(TxnPayment, Transaction)
        .join(Transaction, Transaction.id == TxnPayment.txn_id)
        .filter(TxnPayment.method == PaymentMode.CHEQUE)
        .filter(TxnPayment.cleared_at.is_(None))
        .order_by(Transaction.date.desc(), Transaction.time.desc())
        .all()
    )
    return [
        PendingChequeOut(
            payment_id=str(p.id),
            txn_id=t.id,
            txn_date=t.date,
            amount_php=p.amount_php,
            reference_no=p.reference_no,
            customer=t.customer,
            cashier=t.cashier,
        )
        for p, t in rows
    ]


@router.post("/cheques/{payment_id}/clear")
async def clear_cheque(
    payment_id: str,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    payment = db.query(TxnPayment).filter(TxnPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cheque payment not found")
    if payment.method != PaymentMode.CHEQUE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment is not a cheque")
    if payment.cleared_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cheque already cleared")

    mock = get_mock_date()
    payment.cleared_at = datetime(mock.year, mock.month, mock.day, 6, 0, 0) if mock else datetime.now()
    payment.cleared_by = current_user.username
    db.commit()
    db.refresh(payment)

    return {
        "payment_id": str(payment.id),
        "cleared_at": payment.cleared_at,
        "cleared_by": payment.cleared_by,
    }
