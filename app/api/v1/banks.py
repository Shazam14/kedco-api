from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.api.v1.auth import require_role
from app.models.bank import Bank

router = APIRouter()


class BankOut(BaseModel):
    id: int
    name: str
    code: str
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


class BankIn(BaseModel):
    name: str
    code: str
    sort_order: Optional[int] = 99


@router.get("/banks", response_model=list[BankOut])
def list_banks(db: Session = Depends(get_db)):
    """Public — returns all active banks for payment dropdowns."""
    return db.query(Bank).filter_by(is_active=True).order_by(Bank.sort_order).all()


@router.get("/admin/banks", response_model=list[BankOut])
def list_all_banks(db: Session = Depends(get_db), _=Depends(require_role(["admin", "supervisor"]))):
    """Admin — returns all banks including inactive."""
    return db.query(Bank).order_by(Bank.sort_order).all()


@router.post("/admin/banks", response_model=BankOut, status_code=201)
def create_bank(data: BankIn, db: Session = Depends(get_db), _=Depends(require_role(["admin"]))):
    if db.query(Bank).filter_by(code=data.code.upper()).first():
        raise HTTPException(400, f"Bank code {data.code} already exists")
    bank = Bank(name=data.name, code=data.code.upper(), sort_order=data.sort_order)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


@router.patch("/admin/banks/{bank_id}")
def update_bank(bank_id: int, data: dict, db: Session = Depends(get_db), _=Depends(require_role(["admin"]))):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank not found")
    for field in ("name", "is_active", "sort_order"):
        if field in data:
            setattr(bank, field, data[field])
    db.commit()
    return {"message": "Updated"}
