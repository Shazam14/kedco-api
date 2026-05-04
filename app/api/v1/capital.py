from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.today import get_today
from app.models.capital import PhpCapitalEntry
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/capital", tags=["capital"])


class CapitalEntryIn(BaseModel):
    amount_php: float                    # signed: + injection, - withdrawal
    note:       Optional[str] = None
    entry_date: Optional[date_type] = None  # defaults to today (PHT)


class CapitalEntryOut(BaseModel):
    id:         str
    amount_php: float
    note:       Optional[str]
    entry_date: date_type
    created_by: str
    created_at: datetime


class CapitalLedgerOut(BaseModel):
    running_total: float
    entries:       list[CapitalEntryOut]


def _to_out(e: PhpCapitalEntry) -> CapitalEntryOut:
    return CapitalEntryOut(
        id=str(e.id),
        amount_php=e.amount_php,
        note=e.note,
        entry_date=e.entry_date,
        created_by=e.created_by,
        created_at=e.created_at,
    )


@router.get("/php", response_model=CapitalLedgerOut)
async def get_php_capital(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(PhpCapitalEntry)
        .order_by(PhpCapitalEntry.entry_date.desc(), PhpCapitalEntry.created_at.desc())
        .all()
    )
    running_total = round(sum(e.amount_php for e in entries), 2)
    return CapitalLedgerOut(
        running_total=running_total,
        entries=[_to_out(e) for e in entries],
    )


@router.post("/php", response_model=CapitalEntryOut, status_code=status.HTTP_201_CREATED)
async def add_php_capital_entry(
    payload: CapitalEntryIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.amount_php == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero.")

    entry = PhpCapitalEntry(
        amount_php=payload.amount_php,
        note=payload.note,
        entry_date=payload.entry_date or get_today(),
        created_by=current_user.username,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_out(entry)
