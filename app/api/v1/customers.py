from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.api.v1.auth import require_role, TokenData
from app.models.customer import Customer

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
