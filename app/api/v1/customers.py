from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime, date

from app.core.database import get_db
from app.api.v1.auth import require_role, TokenData
from app.models.customer import Customer
from app.models.transaction import Transaction, PaymentStatus

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerOut(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=300)


@router.get("", response_model=list[CustomerOut])
def list_customers(
    q: Optional[str] = Query(None, description="Search by name or phone (case-insensitive substring)"),
    limit: int = Query(20, ge=1, le=50),
    _user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    """Autocomplete-friendly customer search. Excludes merged dupes."""
    query = db.query(Customer).filter(
        Customer.is_active.is_(True),
        Customer.merged_into_id.is_(None),
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    return query.order_by(Customer.name).limit(limit).all()


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    data: CustomerIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Customer name is required")
    customer = Customer(
        name=name,
        phone=(data.phone or None),
        notes=(data.notes or None),
        created_by=current_user.username,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    _user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# ── Admin-only: enriched list for /admin/customers ──────────────────────────

class CustomerWithStatsOut(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    txn_count: int
    total_volume_php: float
    last_txn_date: Optional[date] = None


admin_router = APIRouter(prefix="/admin/customers", tags=["customers-admin"])


@admin_router.get("", response_model=list[CustomerWithStatsOut])
def admin_list_customers(
    q: Optional[str] = Query(None, description="Search by name or phone"),
    include_inactive: bool = Query(False, description="Include soft-deleted/merged customers"),
    limit: int = Query(100, ge=1, le=500),
    _user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """
    Admin/supervisor list of customers with per-customer aggregates:
    txn_count, total_volume_php, last_txn_date. Used by /admin/customers.

    Volume + count exclude PENDING transactions — those haven't moved money.
    Sorted by total_volume_php desc so Ken's biggest customers surface first.
    """
    txn_join_cond = (
        (Transaction.customer_id == Customer.id)
        & (Transaction.payment_status != PaymentStatus.PENDING)
    )
    query = (
        db.query(
            Customer,
            func.count(Transaction.id).label("txn_count"),
            func.coalesce(func.sum(Transaction.php_amt), 0.0).label("total_volume_php"),
            func.max(Transaction.date).label("last_txn_date"),
        )
        .outerjoin(Transaction, txn_join_cond)
        .group_by(Customer.id)
    )
    if not include_inactive:
        query = query.filter(Customer.is_active.is_(True), Customer.merged_into_id.is_(None))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))

    rows = query.order_by(
        func.coalesce(func.sum(Transaction.php_amt), 0.0).desc(),
        Customer.name,
    ).limit(limit).all()

    return [
        CustomerWithStatsOut(
            id=c.id, name=c.name, phone=c.phone, notes=c.notes,
            is_active=c.is_active, created_by=c.created_by, created_at=c.created_at,
            txn_count=int(txn_count or 0),
            total_volume_php=float(total_volume_php or 0),
            last_txn_date=last_txn_date,
        )
        for c, txn_count, total_volume_php, last_txn_date in rows
    ]


class MergeIn(BaseModel):
    duplicate_ids: list[UUID] = Field(min_length=1)


class MergeOut(BaseModel):
    canonical_id: UUID
    merged_count: int
    transactions_repointed: int


@admin_router.post("/{canonical_id}/merge", response_model=MergeOut)
def merge_customers(
    canonical_id: UUID,
    data: MergeIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Repoint every `transactions.customer_id` from each dupe to the canonical
    row, then soft-delete the dupes (is_active=False, merged_into_id set).

    Admin-only. Rejects:
      • canonical missing / inactive / already merged
      • canonical id appearing in duplicate_ids (no self-merge)
      • any duplicate id missing
      • any duplicate already merged elsewhere (no chain merges — would
        leave existing pointers ambiguous)
    """
    canonical = db.query(Customer).filter_by(id=canonical_id).first()
    if not canonical:
        raise HTTPException(404, "Canonical customer not found")
    if not canonical.is_active or canonical.merged_into_id is not None:
        raise HTTPException(400, "Canonical customer is inactive or already merged")

    dupe_ids = list({d for d in data.duplicate_ids})  # de-dupe the request itself
    if canonical_id in dupe_ids:
        raise HTTPException(400, "Cannot merge a customer into itself")

    dupes = db.query(Customer).filter(Customer.id.in_(dupe_ids)).all()
    if len(dupes) != len(dupe_ids):
        raise HTTPException(400, "One or more duplicate ids not found")
    for d in dupes:
        if d.merged_into_id is not None:
            raise HTTPException(
                400,
                f"Customer {d.id} is already merged into {d.merged_into_id} — "
                "merge chains are not supported",
            )

    repointed = (
        db.query(Transaction)
        .filter(Transaction.customer_id.in_(dupe_ids))
        .update({Transaction.customer_id: canonical_id}, synchronize_session=False)
    )
    for d in dupes:
        d.is_active = False
        d.merged_into_id = canonical_id
    db.commit()

    return MergeOut(
        canonical_id=canonical_id,
        merged_count=len(dupes),
        transactions_repointed=int(repointed),
    )
