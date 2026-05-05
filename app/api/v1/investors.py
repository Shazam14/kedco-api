from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.models.investor import Investor
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/investors", tags=["investors"])


class InvestorIn(BaseModel):
    name:             str
    capital_php:      float
    monthly_rate_pct: float
    note:             Optional[str] = None


class InvestorPatch(BaseModel):
    name:             Optional[str]   = None
    capital_php:      Optional[float] = None
    monthly_rate_pct: Optional[float] = None
    note:             Optional[str]   = None


class InvestorOut(BaseModel):
    id:               str
    name:             str
    capital_php:      float
    monthly_rate_pct: float
    note:             Optional[str]
    created_by:       str
    created_at:       datetime
    updated_at:       datetime


def _to_out(i: Investor) -> InvestorOut:
    return InvestorOut(
        id=str(i.id),
        name=i.name,
        capital_php=i.capital_php,
        monthly_rate_pct=i.monthly_rate_pct,
        note=i.note,
        created_by=i.created_by,
        created_at=i.created_at,
        updated_at=i.updated_at,
    )


def _validate(name: str | None, capital: float | None, rate: float | None) -> None:
    if name is not None and not name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be blank.")
    if capital is not None and capital <= 0:
        raise HTTPException(status_code=400, detail="Capital must be positive.")
    if rate is not None and rate < 0:
        raise HTTPException(status_code=400, detail="Rate cannot be negative.")


@router.get("", response_model=list[InvestorOut])
async def list_investors(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    rows = db.query(Investor).order_by(Investor.created_at.asc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=InvestorOut, status_code=status.HTTP_201_CREATED)
async def create_investor(
    payload: InvestorIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    _validate(payload.name, payload.capital_php, payload.monthly_rate_pct)
    inv = Investor(
        name=payload.name.strip(),
        capital_php=payload.capital_php,
        monthly_rate_pct=payload.monthly_rate_pct,
        note=(payload.note or "").strip() or None,
        created_by=current_user.username,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _to_out(inv)


@router.patch("/{investor_id}", response_model=InvestorOut)
async def update_investor(
    investor_id: str,
    payload: InvestorPatch,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(investor_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Investor not found.")

    inv = db.query(Investor).filter(Investor.id == uid).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investor not found.")

    _validate(payload.name, payload.capital_php, payload.monthly_rate_pct)
    if payload.name is not None:             inv.name             = payload.name.strip()
    if payload.capital_php is not None:      inv.capital_php      = payload.capital_php
    if payload.monthly_rate_pct is not None: inv.monthly_rate_pct = payload.monthly_rate_pct
    if payload.note is not None:             inv.note             = payload.note.strip() or None

    db.commit()
    db.refresh(inv)
    return _to_out(inv)


@router.delete("/{investor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investor(
    investor_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(investor_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Investor not found.")

    inv = db.query(Investor).filter(Investor.id == uid).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investor not found.")
    db.delete(inv)
    db.commit()
    return None
