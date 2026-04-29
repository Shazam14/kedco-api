from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import uuid

from app.core.database import get_db
from app.api.v1.auth import require_role, TokenData
from app.models.transaction import (
    RiderDispatch, RiderDispatchItem, RiderRemitItem, RiderDispatchTopup,
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
    items: list[CurrencyItem] = []
    notes: Optional[str] = None

class TopupIn(BaseModel):
    amount_php: float
    notes: Optional[str] = None

class TopupOut(BaseModel):
    id: str
    amount_php: float
    time: Optional[str]
    dispatched_by: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True

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
    remit_php: Optional[float]
    items: list[ItemOut]
    remit_items: list[ItemOut]
    topups: list[TopupOut] = []
    notes: Optional[str]
    dispatched_by: Optional[str]

    class Config:
        from_attributes = True

class RemitIn(BaseModel):
    dispatch_id: str
    cash_php_remaining: float
    items: list[CurrencyItem]   # forex the rider is returning

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
    # PHP is cash, not forex inventory — coerce PHP line items into cash_php
    php_in_items = sum(item.amount for item in data.items if item.currency.upper() == "PHP")
    forex_items  = [item for item in data.items if item.currency.upper() != "PHP"]
    total_cash_php = (data.cash_php or 0) + php_in_items

    if total_cash_php <= 0 and not forex_items:
        raise HTTPException(400, "At least cash or one forex item is required")

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
        cash_php=total_cash_php,
        notes=data.notes,
        dispatched_by=current_user.username,
    )
    db.add(dispatch)
    db.flush()

    for item in forex_items:
        db.add(RiderDispatchItem(
            id=uuid.uuid4(),
            dispatch_id=dispatch.id,
            currency=item.currency.upper(),
            amount=item.amount,
        ))

    db.commit()
    db.refresh(dispatch)
    return _dispatch_out(dispatch, db)


@router.post("/dispatches/{dispatch_id}/topup", response_model=DispatchOut)
def topup_dispatch(
    dispatch_id: str,
    data: TopupIn,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
):
    if data.amount_php <= 0:
        raise HTTPException(400, "Top-up amount must be positive")

    dispatch = db.query(RiderDispatch).filter_by(id=dispatch_id).first()
    if not dispatch:
        raise HTTPException(404, "Dispatch not found")
    if dispatch.status != DispatchStatus.IN_FIELD:
        raise HTTPException(400, "Can only top up an IN_FIELD dispatch")

    db.add(RiderDispatchTopup(
        id=uuid.uuid4(),
        dispatch_id=dispatch.id,
        amount_php=data.amount_php,
        time=datetime.now().strftime("%I:%M %p"),
        dispatched_by=current_user.username,
        notes=data.notes,
    ))
    dispatch.cash_php = (dispatch.cash_php or 0) + data.amount_php

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


# ── Rider remit (end of day) ───────────────────────────────────────────────────

@router.post("/remit", response_model=DispatchOut)
def submit_remit(
    data: RemitIn,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role("rider")),
):
    dispatch = db.query(RiderDispatch).filter_by(
        id=data.dispatch_id,
        rider_username=current_user.username,
        status=DispatchStatus.IN_FIELD,
    ).first()
    if not dispatch:
        raise HTTPException(404, "Active dispatch not found")

    dispatch.status   = DispatchStatus.REMITTED
    dispatch.remit_php = data.cash_php_remaining
    dispatch.return_time = datetime.now().strftime("%I:%M %p")

    # Clear any previous remit items (idempotent)
    db.query(RiderRemitItem).filter_by(dispatch_id=dispatch.id).delete()
    for item in data.items:
        db.add(RiderRemitItem(
            id=uuid.uuid4(),
            dispatch_id=dispatch.id,
            currency=item.currency.upper(),
            amount=item.amount,
        ))

    db.commit()
    db.refresh(dispatch)
    return _dispatch_out(dispatch, db)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dispatch_out(d: RiderDispatch, db: Session) -> DispatchOut:
    dispatch_items = db.query(RiderDispatchItem).filter_by(dispatch_id=d.id).order_by(RiderDispatchItem.created_at).all()
    remit_items    = db.query(RiderRemitItem).filter_by(dispatch_id=d.id).order_by(RiderRemitItem.created_at).all()
    topups         = db.query(RiderDispatchTopup).filter_by(dispatch_id=d.id).order_by(RiderDispatchTopup.created_at).all()
    return DispatchOut(
        id=str(d.id),
        date=d.date,
        rider_username=d.rider_username or "",
        rider_name=d.rider_name,
        status=d.status.value if hasattr(d.status, 'value') else d.status,
        dispatch_time=d.dispatch_time,
        return_time=d.return_time,
        cash_php=d.cash_php or 0,
        remit_php=d.remit_php,
        items=[ItemOut(currency=i.currency, amount=i.amount) for i in dispatch_items],
        remit_items=[ItemOut(currency=i.currency, amount=i.amount) for i in remit_items],
        topups=[TopupOut(
            id=str(t.id),
            amount_php=t.amount_php,
            time=t.time,
            dispatched_by=t.dispatched_by,
            notes=t.notes,
        ) for t in topups],
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
