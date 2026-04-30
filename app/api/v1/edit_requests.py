from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime, date
from uuid import UUID
import uuid

from app.core.database import get_db
from app.models.transaction import Transaction, TxnPayment
from app.models.audit import AuditLog
from app.models.edit_request import TransactionEditRequest, EditRequestStatus
from app.api.v1.auth import require_role, TokenData
from app.api.v1.transactions import _validate_customer_id
from app.core.today import get_today
from app.services.email import notify_edit_request

router = APIRouter(tags=["edit-requests"])


class EditRequestIn(BaseModel):
    type:          Optional[Literal["BUY", "SELL"]] = None
    customer:      Optional[str]   = None
    customer_id:   Optional[UUID]  = None
    payment_mode:  Optional[str]   = None
    rate:          Optional[float] = None
    foreign_amt:   Optional[float] = None
    official_rate: Optional[float] = None
    referrer:      Optional[str]   = None
    branch_id:     Optional[str]   = None
    note:          Optional[str]   = None


class RejectIn(BaseModel):
    rejection_note: Optional[str] = None


def _txn_snapshot(r: Transaction) -> dict:
    return {
        "customer":      r.customer,
        "customer_id":   str(r.customer_id) if r.customer_id else None,
        "payment_mode":  str(r.payment_mode),
        "rate":          r.rate,
        "foreign_amt":   r.foreign_amt,
        "php_amt":       r.php_amt,
        "than":          r.than,
        "official_rate": r.official_rate,
        "referrer":      r.referrer,
        "branch_id":     r.branch_id,
        "payments": [
            {"method": str(p.method), "amount_php": p.amount_php, "status": str(p.status)}
            for p in (r.payments or [])
        ],
    }


def _scale_slices(slices: list[TxnPayment], new_php_amt: float) -> None:
    """
    Scale TxnPayment.amount_php proportionally so the slice sum equals new_php_amt.
    Single-slice (legacy) → set directly. Multi-slice → ratio scale, with rounding
    residue absorbed by the last slice so the sum stays exact.
    """
    if not slices:
        return
    if len(slices) == 1:
        slices[0].amount_php = round(new_php_amt, 2)
        return
    old_total = sum(s.amount_php for s in slices)
    if old_total <= 0:
        # Defensive: can't scale a zero-sum split. Put the new total on the first slice.
        for s in slices:
            s.amount_php = 0.0
        slices[0].amount_php = round(new_php_amt, 2)
        return
    ratio = new_php_amt / old_total
    running = 0.0
    for s in slices[:-1]:
        s.amount_php = round(s.amount_php * ratio, 2)
        running += s.amount_php
    slices[-1].amount_php = round(new_php_amt - running, 2)


def _req_out(r: TransactionEditRequest) -> dict:
    return {
        "id":             str(r.id),
        "txn_id":         r.txn_id,
        "txn_date":       r.txn_date.isoformat() if r.txn_date else None,
        "requested_by":   r.requested_by,
        "current_values": r.current_values,
        "proposed":       r.proposed,
        "note":           r.note,
        "status":         r.status,
        "reviewed_by":    r.reviewed_by,
        "reviewed_at":    r.reviewed_at.isoformat() if r.reviewed_at else None,
        "rejection_note": r.rejection_note,
        "created_at":     r.created_at.isoformat() if r.created_at else None,
    }


# ── Cashier: submit edit request ────────────────────────────────────────────

@router.post("/transactions/{txn_id}/edit-request")
async def submit_edit_request(
    txn_id: str,
    body: EditRequestIn,
    background: BackgroundTasks,
    current_user: TokenData = Depends(require_role("cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    txn = db.query(Transaction).filter_by(id=txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.date != get_today():
        raise HTTPException(status_code=403, detail="Only same-day transactions can be edited")
    if txn.cashier != current_user.username:
        raise HTTPException(status_code=403, detail="You can only request edits on your own transactions")

    existing = db.query(TransactionEditRequest).filter_by(
        txn_id=txn_id, status=EditRequestStatus.PENDING
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A pending edit request already exists for this transaction")

    if body.customer_id is not None:
        _validate_customer_id(body.customer_id, db)

    proposed = {}
    if body.type is not None:          proposed["type"]          = body.type
    if body.customer is not None:      proposed["customer"]      = body.customer or None
    if body.customer_id is not None:   proposed["customer_id"]   = str(body.customer_id)
    if body.payment_mode is not None:  proposed["payment_mode"]  = body.payment_mode
    if body.rate is not None:          proposed["rate"]          = body.rate
    if body.foreign_amt is not None:   proposed["foreign_amt"]   = body.foreign_amt
    if body.official_rate is not None: proposed["official_rate"] = body.official_rate or None
    if body.referrer is not None:      proposed["referrer"]      = body.referrer or None
    if body.branch_id is not None:     proposed["branch_id"]     = body.branch_id or None

    if not proposed:
        raise HTTPException(status_code=400, detail="No changes submitted")

    req = TransactionEditRequest(
        id=uuid.uuid4(),
        txn_id=txn_id,
        txn_date=txn.date,
        requested_by=current_user.username,
        current_values=_txn_snapshot(txn),
        proposed=proposed,
        note=body.note,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    background.add_task(notify_edit_request, txn_id, current_user.username, proposed, body.note)

    return _req_out(req)


# ── Cashier: my pending edit request IDs for today ──────────────────────────

@router.get("/transactions/my-pending-edits")
async def my_pending_edits(
    current_user: TokenData = Depends(require_role("cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    rows = db.query(TransactionEditRequest).filter_by(
        requested_by=current_user.username,
        status=EditRequestStatus.PENDING,
    ).filter(TransactionEditRequest.txn_date == get_today()).all()
    return [str(r.txn_id) for r in rows]


# ── Admin: list edit requests ────────────────────────────────────────────────

@router.get("/admin/edit-requests")
async def list_edit_requests(
    status: Optional[str] = None,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    q = db.query(TransactionEditRequest).order_by(TransactionEditRequest.created_at.desc())
    if status:
        q = q.filter(TransactionEditRequest.status == status.upper())
    return [_req_out(r) for r in q.limit(200).all()]


# ── Admin: pending count ─────────────────────────────────────────────────────

@router.get("/admin/edit-requests/pending-count")
async def pending_count(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    n = db.query(TransactionEditRequest).filter_by(status=EditRequestStatus.PENDING).count()
    return {"count": n}


# ── Admin: approve ───────────────────────────────────────────────────────────

@router.post("/admin/edit-requests/{req_id}/approve")
async def approve_edit_request(
    req_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    req = db.query(TransactionEditRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Edit request not found")
    if req.status != EditRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    txn = db.query(Transaction).filter_by(id=req.txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Original transaction not found")

    old_snapshot = _txn_snapshot(txn)

    p = req.proposed
    if "type"          in p: txn.type          = p["type"]
    if "customer"      in p: txn.customer      = p["customer"]
    if "customer_id"   in p:
        cid = UUID(p["customer_id"]) if p["customer_id"] else None
        if cid is not None:
            _validate_customer_id(cid, db)
        txn.customer_id = cid
    if "payment_mode"  in p: txn.payment_mode  = p["payment_mode"]
    if "rate"          in p: txn.rate          = p["rate"]
    if "foreign_amt"   in p: txn.foreign_amt   = p["foreign_amt"]
    if "official_rate" in p: txn.official_rate = p["official_rate"]
    if "referrer"      in p: txn.referrer      = p["referrer"]
    if "branch_id"     in p: txn.branch_id     = p["branch_id"]

    if "rate" in p or "foreign_amt" in p or "type" in p:
        txn.php_amt = round(txn.foreign_amt * txn.rate, 2)
        if str(txn.type) == "SELL":
            txn.than = round((txn.rate - txn.daily_avg_cost) * txn.foreign_amt, 2)
        else:
            txn.than = 0.0
        # Keep slice sum aligned with new php_amt so reports stay consistent.
        _scale_slices(list(txn.payments or []), txn.php_amt)

    req.status      = EditRequestStatus.APPROVED
    req.reviewed_by = current_user.username
    req.reviewed_at = datetime.now()

    db.add(AuditLog(
        id=uuid.uuid4(),
        table_name="transactions",
        record_id=req.txn_id,
        action="UPDATE",
        changed_by=current_user.username,
        old_value=old_snapshot,
        new_value=_txn_snapshot(txn),
        note=f"Approved edit request from {req.requested_by}",
    ))

    db.commit()
    return {"status": "approved"}


# ── Admin: reject ────────────────────────────────────────────────────────────

@router.post("/admin/edit-requests/{req_id}/reject")
async def reject_edit_request(
    req_id: str,
    body: RejectIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    req = db.query(TransactionEditRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Edit request not found")
    if req.status != EditRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    req.status         = EditRequestStatus.REJECTED
    req.reviewed_by    = current_user.username
    req.reviewed_at    = datetime.now()
    req.rejection_note = body.rejection_note

    db.commit()
    return {"status": "rejected"}
