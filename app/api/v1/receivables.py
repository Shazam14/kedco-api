from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, date, timezone
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.models.receivable import PendingReceivable
from app.models.audit import AuditLog
from app.api.v1.auth import require_role, TokenData


router = APIRouter(prefix="/receivables", tags=["receivables"])


_METHODS = {"CHEQUE", "GCASH", "PNB", "TRANSFER", "WALKIN", "UNKNOWN"}
_BANKS   = {"GPO", "CBC", "MBTC"}
_STATUSES = {"PENDING", "CLEARED", "BAD_DEBT"}


class ReceivableIn(BaseModel):
    customer_name: str
    amount_php:    float
    method:        str = "UNKNOWN"
    bank_account:  str
    entry_date:    Optional[date] = None
    note:          Optional[str]  = None
    status:        Optional[str]  = "PENDING"


class ReceivablePatch(BaseModel):
    customer_name: Optional[str]   = None
    amount_php:    Optional[float] = None
    method:        Optional[str]   = None
    bank_account:  Optional[str]   = None
    entry_date:    Optional[date]  = None
    note:          Optional[str]   = None
    status:        Optional[str]   = None


class ReceivableOut(BaseModel):
    id:            str
    customer_name: str
    amount_php:    float
    method:        str
    bank_account:  str
    entry_date:    Optional[date]
    status:        str
    note:          Optional[str]
    cleared_at:    Optional[datetime]
    cleared_by:    Optional[str]
    created_by:    str
    created_at:    datetime


def _validate_enums(method: Optional[str], bank: Optional[str], status_: Optional[str]) -> None:
    if method is not None and method not in _METHODS:
        raise HTTPException(status_code=400, detail=f"Invalid method. Must be one of: {sorted(_METHODS)}")
    if bank is not None and bank not in _BANKS:
        raise HTTPException(status_code=400, detail=f"Invalid bank_account. Must be one of: {sorted(_BANKS)}")
    if status_ is not None and status_ not in _STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {sorted(_STATUSES)}")


def _out(r: PendingReceivable) -> ReceivableOut:
    return ReceivableOut(
        id=str(r.id),
        customer_name=r.customer_name,
        amount_php=r.amount_php,
        method=r.method,
        bank_account=r.bank_account,
        entry_date=r.entry_date,
        status=r.status,
        note=r.note,
        cleared_at=r.cleared_at,
        cleared_by=r.cleared_by,
        created_by=r.created_by,
        created_at=r.created_at,
    )


@router.get("/", response_model=list[ReceivableOut])
async def list_receivables(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """All receivables, newest first. Frontend groups by bank_account."""
    rows = (
        db.query(PendingReceivable)
        .order_by(PendingReceivable.created_at.desc())
        .all()
    )
    return [_out(r) for r in rows]


@router.post("/", response_model=ReceivableOut, status_code=status.HTTP_201_CREATED)
async def create_receivable(
    payload: ReceivableIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    name = (payload.customer_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="customer_name cannot be blank.")
    if payload.amount_php is None:
        raise HTTPException(status_code=400, detail="amount_php is required.")
    _validate_enums(payload.method, payload.bank_account, payload.status)
    r = PendingReceivable(
        customer_name=name,
        amount_php=round(float(payload.amount_php), 2),
        method=payload.method or "UNKNOWN",
        bank_account=payload.bank_account,
        entry_date=payload.entry_date,
        status=payload.status or "PENDING",
        note=(payload.note or "").strip() or None,
        created_by=current_user.username,
    )
    db.add(r)
    db.flush()
    db.add(AuditLog(
        id=uuid.uuid4(), table_name="pending_receivables", record_id=str(r.id),
        action="CREATE", changed_by=current_user.username,
        old_value=None,
        new_value={
            "customer_name": r.customer_name, "amount_php": r.amount_php,
            "method": r.method, "bank_account": r.bank_account,
            "status": r.status, "note": r.note,
        },
        note="receivable.create",
    ))
    db.commit()
    db.refresh(r)
    return _out(r)


@router.patch("/{receivable_id}", response_model=ReceivableOut)
async def update_receivable(
    receivable_id: str,
    payload: ReceivablePatch,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(receivable_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Receivable not found.")
    r = db.query(PendingReceivable).filter(PendingReceivable.id == uid).first()
    if not r:
        raise HTTPException(status_code=404, detail="Receivable not found.")

    _validate_enums(payload.method, payload.bank_account, payload.status)

    old = {
        "customer_name": r.customer_name, "amount_php": r.amount_php,
        "method": r.method, "bank_account": r.bank_account,
        "status": r.status, "note": r.note,
    }

    if payload.customer_name is not None:
        name = payload.customer_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="customer_name cannot be blank.")
        r.customer_name = name
    if payload.amount_php is not None:
        r.amount_php = round(float(payload.amount_php), 2)
    if payload.method is not None:
        r.method = payload.method
    if payload.bank_account is not None:
        r.bank_account = payload.bank_account
    if payload.entry_date is not None:
        r.entry_date = payload.entry_date
    if payload.note is not None:
        r.note = payload.note.strip() or None
    if payload.status is not None:
        # Status transitions stamp cleared_at when moving to CLEARED.
        if payload.status == "CLEARED" and r.status != "CLEARED":
            r.cleared_at = datetime.now(timezone.utc)
            r.cleared_by = current_user.username
        if payload.status != "CLEARED":
            r.cleared_at = None
            r.cleared_by = None
        r.status = payload.status

    new = {
        "customer_name": r.customer_name, "amount_php": r.amount_php,
        "method": r.method, "bank_account": r.bank_account,
        "status": r.status, "note": r.note,
    }
    db.add(AuditLog(
        id=uuid.uuid4(), table_name="pending_receivables", record_id=str(r.id),
        action="UPDATE", changed_by=current_user.username,
        old_value=old, new_value=new, note="receivable.update",
    ))
    db.commit()
    db.refresh(r)
    return _out(r)


@router.delete("/{receivable_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_receivable(
    receivable_id: str,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(receivable_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Receivable not found.")
    r = db.query(PendingReceivable).filter(PendingReceivable.id == uid).first()
    if not r:
        raise HTTPException(status_code=404, detail="Receivable not found.")
    db.add(AuditLog(
        id=uuid.uuid4(), table_name="pending_receivables", record_id=str(r.id),
        action="DELETE", changed_by=current_user.username,
        old_value={
            "customer_name": r.customer_name, "amount_php": r.amount_php,
            "bank_account": r.bank_account, "status": r.status,
        },
        new_value=None, note="receivable.delete",
    ))
    db.delete(r)
    db.commit()
