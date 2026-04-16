from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date as date_type
from typing import Optional
from pydantic import BaseModel, field_validator
import uuid

from app.core.database import get_db
from app.models.passbook import PassbookEntry
from app.models.bank import Bank
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/passbook", tags=["passbook"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class DepositIn(BaseModel):
    bank_id:        int
    amount:         float
    deposited_date: date_type
    notes:          Optional[str] = None

    @field_validator("amount")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive.")
        return v


class EntryOut(BaseModel):
    id:             str
    bank_id:        int
    bank_name:      str
    bank_code:      str
    amount:         float
    deposited_date: date_type
    logged_by:      str
    notes:          Optional[str]
    running_total:  float
    created_at:     str


class BankSummary(BaseModel):
    bank_id:   int
    bank_name: str
    bank_code: str
    total:     float
    entries:   list[EntryOut]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=EntryOut)
async def log_deposit(
    payload: DepositIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor", "cashier")),
    db: Session = Depends(get_db),
):
    bank = db.query(Bank).filter_by(id=payload.bank_id, is_active=True).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found or inactive.")

    entry = PassbookEntry(
        id=uuid.uuid4(),
        bank_id=payload.bank_id,
        amount=payload.amount,
        deposited_date=payload.deposited_date,
        logged_by=current_user.username,
        notes=payload.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    # Running total for this bank up to and including this entry
    total = db.query(PassbookEntry).filter_by(bank_id=payload.bank_id).with_entities(
        PassbookEntry.amount
    ).all()
    running = sum(r.amount for r in total)

    return EntryOut(
        id=str(entry.id),
        bank_id=bank.id,
        bank_name=bank.name,
        bank_code=bank.code,
        amount=entry.amount,
        deposited_date=entry.deposited_date,
        logged_by=entry.logged_by,
        notes=entry.notes,
        running_total=running,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
    )


@router.get("/", response_model=list[BankSummary])
async def get_passbook(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    banks = db.query(Bank).filter_by(is_active=True).order_by(Bank.sort_order, Bank.name).all()
    result = []
    for bank in banks:
        entries = (
            db.query(PassbookEntry)
            .filter_by(bank_id=bank.id)
            .order_by(PassbookEntry.deposited_date.asc(), PassbookEntry.created_at.asc())
            .all()
        )
        running = 0.0
        out_entries = []
        for e in entries:
            running += e.amount
            out_entries.append(EntryOut(
                id=str(e.id),
                bank_id=bank.id,
                bank_name=bank.name,
                bank_code=bank.code,
                amount=e.amount,
                deposited_date=e.deposited_date,
                logged_by=e.logged_by,
                notes=e.notes,
                running_total=running,
                created_at=e.created_at.isoformat() if e.created_at else "",
            ))
        result.append(BankSummary(
            bank_id=bank.id,
            bank_name=bank.name,
            bank_code=bank.code,
            total=running,
            entries=out_entries,
        ))
    return result


@router.get("/my-deposits", response_model=list[EntryOut])
async def my_deposits(
    current_user: TokenData = Depends(require_role("admin", "supervisor", "cashier")),
    db: Session = Depends(get_db),
):
    """Recent deposits logged by the calling cashier (last 30)."""
    entries = (
        db.query(PassbookEntry)
        .filter_by(logged_by=current_user.username)
        .order_by(PassbookEntry.deposited_date.desc(), PassbookEntry.created_at.desc())
        .limit(30)
        .all()
    )
    bank_cache: dict[int, Bank] = {}

    def get_bank(bid: int) -> Bank:
        if bid not in bank_cache:
            bank_cache[bid] = db.query(Bank).filter_by(id=bid).first()
        return bank_cache[bid]

    result = []
    for e in entries:
        bank = get_bank(e.bank_id)
        result.append(EntryOut(
            id=str(e.id),
            bank_id=e.bank_id,
            bank_name=bank.name if bank else "—",
            bank_code=bank.code if bank else "—",
            amount=e.amount,
            deposited_date=e.deposited_date,
            logged_by=e.logged_by,
            notes=e.notes,
            running_total=0,  # not relevant for cashier view
            created_at=e.created_at.isoformat() if e.created_at else "",
        ))
    return result
