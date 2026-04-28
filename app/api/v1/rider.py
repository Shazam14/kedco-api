from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import uuid

from app.core.database import get_db
from app.api.v1.auth import require_role, TokenData
from app.models.transaction import (
    RiderDispatch, RiderDispatchItem, RiderRemitItem,
    RiderBorrow, Transaction, DispatchStatus, PaymentStatus,
)
from app.models.user import User
from app.core.today import get_today

router = APIRouter(prefix="/rider", tags=["rider"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class CurrencyItem(BaseModel):
    currency: str
    amount: float

class DispatchIn(BaseModel):
    rider_username: str
    cash_php: float = 0
    items: list[CurrencyItem]
    notes: Optional[str] = None

class RemitIn(BaseModel):
    items: list[CurrencyItem]

class ItemOut(BaseModel):
    currency: str
    amount: float

class DispatchOut(BaseModel):
    id: str
    date: date
    rider_username: str
    rider_name: str
    status: str
    dispatch_time: Optional[str]
    return_time: Optional[str]
    cash_php: float
    items: list[ItemOut]
    remit_items: list[ItemOut]
    notes: Optional[str]
    dispatched_by: Optional[str]

    class Config:
        from_attributes = True

class BorrowIn(BaseModel):
    dispatch_id: str
    source_type: str   # BRANCH | RIDER
    source_name: str
    amount_php: float
    notes: Optional[str] = None

class BorrowOut(BaseModel):
    id: str
    dispatch_id: str
    source_type: str
    source_name: str
    amount_php: float
    is_returned: str
    notes: Optional[str]

    class Config:
        from_attributes = True


# ── Dispatch endpoints ─────────────────────────────────────────────────────────

@router.get("/dispatches/today", response_model=list[DispatchOut])
def list_today_dispatches(
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_role("admin", "supervisor")),
):
    rows = db.query(RiderDispatch).filter_by(date=get_today()).order_by(RiderDispatch.created_at).all()
    return [_dispatch_out(r, db) for r in rows]


@router.post("/dispatches", response_model=DispatchOut, status_code=201)
def dispatch_rider(
    data: DispatchIn,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
):
    if not data.items:
        raise HTTPException(400, "At least one currency item is required")

    rider = db.query(User).filter_by(username=data.rider_username, role="rider").first()
    if not rider:
        raise HTTPException(400, f"Rider '{data.rider_username}' not found")

    existing = db.query(RiderDispatch).filter_by(
        date=get_today(), rider_username=data.rider_username, status=DispatchStatus.IN_FIELD
    ).first()
    if existing:
        raise HTTPException(400, f"{data.rider_username} is already dispatched today")

    dispatch = RiderDispatch(
        id=uuid.uuid4(),
        date=get_today(),
        rider_username=data.rider_username,
        rider_name=rider.full_name or rider.username,
        status=DispatchStatus.IN_FIELD,
        dispatch_time=datetime.now().strftime("%I:%M %p"),
        cash_php=data.cash_php,
        notes=data.notes,
        dispatched_by=current_user.username,
    )
    db.add(dispatch)
    db.flush()

    for item in data.items:
        db.add(RiderDispatchItem(
            id=uuid.uuid4(),
            dispatch_id=dispatch.id,
            currency=item.currency.upper(),
            amount=item.amount,
        ))

    db.commit()
    db.refresh(dispatch)
    return _dispatch_out(dispatch, db)


@router.patch("/dispatches/{dispatch_id}/return")
def mark_returned(
    dispatch_id: str,
    data: RemitIn,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_role("admin", "supervisor")),
):
    dispatch = db.query(RiderDispatch).filter_by(id=dispatch_id).first()
    if not dispatch:
        raise HTTPException(404, "Dispatch not found")

    dispatch.status = DispatchStatus.RETURNED
    dispatch.return_time = datetime.now().strftime("%I:%M %p")

    for item in data.items:
        db.add(RiderRemitItem(
            id=uuid.uuid4(),
            dispatch_id=dispatch.id,
            currency=item.currency.upper(),
            amount=item.amount,
        ))

    db.commit()
    return _dispatch_out(dispatch, db)


# ── Borrow endpoints ───────────────────────────────────────────────────────────

@router.get("/borrows/{dispatch_id}", response_model=list[BorrowOut])
def list_borrows(
    dispatch_id: str,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_role("admin", "supervisor", "rider")),
):
    rows = db.query(RiderBorrow).filter_by(dispatch_id=dispatch_id).order_by(RiderBorrow.created_at).all()
    return [_borrow_out(r) for r in rows]


@router.post("/borrows", response_model=BorrowOut, status_code=201)
def record_borrow(
    data: BorrowIn,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_role("admin", "supervisor", "rider")),
):
    if data.source_type not in ("BRANCH", "RIDER"):
        raise HTTPException(400, "source_type must be BRANCH or RIDER")
    borrow = RiderBorrow(
        id=uuid.uuid4(),
        dispatch_id=data.dispatch_id,
        source_type=data.source_type,
        source_name=data.source_name,
        amount_php=data.amount_php,
        notes=data.notes,
    )
    db.add(borrow)
    db.commit()
    db.refresh(borrow)
    return _borrow_out(borrow)


@router.patch("/borrows/{borrow_id}/return")
def mark_borrow_returned(
    borrow_id: str,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_role("admin", "supervisor")),
):
    borrow = db.query(RiderBorrow).filter_by(id=borrow_id).first()
    if not borrow:
        raise HTTPException(404, "Borrow not found")
    borrow.is_returned = "Y"
    db.commit()
    return {"message": "Marked as returned"}


# ── Payment confirmation ───────────────────────────────────────────────────────

@router.patch("/transactions/{txn_id}/confirm-payment")
def confirm_payment(
    txn_id: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
):
    txn = db.query(Transaction).filter_by(id=txn_id).first()
    if not txn:
        raise HTTPException(404, "Transaction not found")
    if txn.payment_status == PaymentStatus.RECEIVED:
        raise HTTPException(400, "Payment already confirmed")
    txn.payment_status = PaymentStatus.RECEIVED
    txn.confirmed_by   = current_user.username
    txn.confirmed_at   = datetime.now()
    db.commit()
    return {"message": "Payment confirmed", "confirmed_by": current_user.username}


# ── Rider's own dispatch for today ─────────────────────────────────────────────

@router.get("/my-dispatch")
def my_dispatch(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role("rider")),
):
    dispatch = db.query(RiderDispatch).filter_by(
        date=get_today(),
        rider_username=current_user.username,
        status=DispatchStatus.IN_FIELD,
    ).first()
    if not dispatch:
        return {"dispatch": None}
    return {"dispatch": _dispatch_out(dispatch, db)}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dispatch_out(d: RiderDispatch, db: Session) -> DispatchOut:
    dispatch_items = db.query(RiderDispatchItem).filter_by(dispatch_id=d.id).order_by(RiderDispatchItem.created_at).all()
    remit_items    = db.query(RiderRemitItem).filter_by(dispatch_id=d.id).order_by(RiderRemitItem.created_at).all()
    return DispatchOut(
        id=str(d.id),
        date=d.date,
        rider_username=d.rider_username or "",
        rider_name=d.rider_name,
        status=d.status.value if hasattr(d.status, 'value') else d.status,
        dispatch_time=d.dispatch_time,
        return_time=d.return_time,
        cash_php=d.cash_php or 0,
        items=[ItemOut(currency=i.currency, amount=i.amount) for i in dispatch_items],
        remit_items=[ItemOut(currency=i.currency, amount=i.amount) for i in remit_items],
        notes=d.notes,
        dispatched_by=d.dispatched_by,
    )

def _borrow_out(b: RiderBorrow) -> BorrowOut:
    return BorrowOut(
        id=str(b.id),
        dispatch_id=str(b.dispatch_id),
        source_type=b.source_type,
        source_name=b.source_name,
        amount_php=b.amount_php,
        is_returned=b.is_returned or "N",
        notes=b.notes,
    )
