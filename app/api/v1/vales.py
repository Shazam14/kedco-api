from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.models.capital import ValeParty, ValeEntry
from app.models.investor import Investor
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/vales", tags=["vales"])


class ValePartyIn(BaseModel):
    name: str
    note: Optional[str] = None
    investor_id: Optional[str] = None


class ValePartyPatch(BaseModel):
    name:        Optional[str]  = None
    note:        Optional[str]  = None
    is_active:   Optional[bool] = None
    # Pass investor_id="" or null to unlink.
    investor_id: Optional[str]  = None


class ValePartyOut(BaseModel):
    id:            str
    name:          str
    note:          Optional[str]
    is_active:     bool
    investor_id:   Optional[str]
    investor_name: Optional[str]
    created_by:    str
    created_at:    datetime


class ValeBalanceOut(BaseModel):
    party_id:      str
    name:          str
    is_active:     bool
    balance_php:   float          # signed: + = we owe them, − = they owe us
    entry_count:   int
    investor_id:   Optional[str] = None
    investor_name: Optional[str] = None


class AvailableInvestorOut(BaseModel):
    id:   str
    name: str


class ValeEntryOut(BaseModel):
    id:         str
    party_id:   str
    party_name: str
    amount_php: float           # signed
    note:       Optional[str]
    entry_date: date
    created_by: str
    created_at: datetime


def _party_out(p: ValeParty, db: Session) -> ValePartyOut:
    investor_name = None
    if p.investor_id:
        inv = db.query(Investor).filter(Investor.id == p.investor_id).first()
        if inv:
            investor_name = inv.name
    return ValePartyOut(
        id=str(p.id),
        name=p.name,
        note=p.note,
        is_active=p.is_active,
        investor_id=str(p.investor_id) if p.investor_id else None,
        investor_name=investor_name,
        created_by=p.created_by,
        created_at=p.created_at,
    )


def _resolve_investor(investor_id: Optional[str], db: Session) -> Optional[uuid.UUID]:
    if not investor_id:
        return None
    try:
        iid = uuid.UUID(investor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid investor_id.")
    inv = db.query(Investor).filter(Investor.id == iid).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investor not found.")
    return iid


@router.get("/parties", response_model=list[ValePartyOut])
async def list_parties(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    rows = db.query(ValeParty).order_by(ValeParty.name.asc()).all()
    return [_party_out(r, db) for r in rows]


@router.post("/parties", response_model=ValePartyOut, status_code=status.HTTP_201_CREATED)
async def create_party(
    payload: ValePartyIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be blank.")
    if db.query(ValeParty).filter(func.lower(ValeParty.name) == name.lower()).first():
        raise HTTPException(status_code=409, detail=f"Vale party '{name}' already exists.")
    investor_uid = _resolve_investor(payload.investor_id, db)
    p = ValeParty(
        name=name,
        note=(payload.note or "").strip() or None,
        investor_id=investor_uid,
        created_by=current_user.username,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _party_out(p, db)


@router.patch("/parties/{party_id}", response_model=ValePartyOut)
async def update_party(
    party_id: str,
    payload: ValePartyPatch,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(party_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Vale party not found.")
    p = db.query(ValeParty).filter(ValeParty.id == uid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Vale party not found.")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be blank.")
        clash = (
            db.query(ValeParty)
            .filter(func.lower(ValeParty.name) == name.lower())
            .filter(ValeParty.id != uid)
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail=f"Vale party '{name}' already exists.")
        p.name = name
    if payload.note is not None:
        p.note = payload.note.strip() or None
    if payload.is_active is not None:
        p.is_active = payload.is_active
    # Empty string / None unlinks; non-empty looks up the investor.
    if payload.investor_id is not None:
        p.investor_id = _resolve_investor(payload.investor_id or None, db)
    db.commit()
    db.refresh(p)
    return _party_out(p, db)


@router.get("/available-investors", response_model=list[AvailableInvestorOut])
async def list_available_investors(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """Investors that can be soft-linked to a vale_party. Admin/supervisor only
    so the picker in the vale ledger can populate without exposing capital figures."""
    rows = db.query(Investor).order_by(Investor.name.asc()).all()
    return [AvailableInvestorOut(id=str(r.id), name=r.name) for r in rows]


@router.get("/balances", response_model=list[ValeBalanceOut])
async def list_balances(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """Running balance per party: sum of signed vale_entries.
    + balance = drawer received cash from party (we still owe).
    − balance = drawer returned more than received (over-paid; rare)."""
    parties = db.query(ValeParty).order_by(ValeParty.name.asc()).all()
    rows = []
    for p in parties:
        entries = db.query(ValeEntry).filter(ValeEntry.party_id == p.id).all()
        bal = sum(e.amount_php for e in entries)
        investor_name = None
        if p.investor_id:
            inv = db.query(Investor).filter(Investor.id == p.investor_id).first()
            if inv:
                investor_name = inv.name
        rows.append(ValeBalanceOut(
            party_id=str(p.id),
            name=p.name,
            is_active=p.is_active,
            balance_php=round(bal, 2),
            entry_count=len(entries),
            investor_id=str(p.investor_id) if p.investor_id else None,
            investor_name=investor_name,
        ))
    return rows


@router.get("/parties/{party_id}/entries", response_model=list[ValeEntryOut])
async def list_entries(
    party_id: str,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(party_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Vale party not found.")
    p = db.query(ValeParty).filter(ValeParty.id == uid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Vale party not found.")
    entries = (
        db.query(ValeEntry)
        .filter(ValeEntry.party_id == uid)
        .order_by(ValeEntry.entry_date.desc(), ValeEntry.created_at.desc())
        .all()
    )
    return [
        ValeEntryOut(
            id=str(e.id),
            party_id=str(e.party_id),
            party_name=p.name,
            amount_php=e.amount_php,
            note=e.note,
            entry_date=e.entry_date,
            created_by=e.created_by,
            created_at=e.created_at,
        )
        for e in entries
    ]
