from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone, date
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.core.today import get_today
from app.models.expense import Expense, EXPENSE_CATEGORIES
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/expenses", tags=["expenses"])


class ExpenseIn(BaseModel):
    amount_php: float
    category: str
    description: Optional[str] = None
    referrer: Optional[str] = None


class ExpensePatch(BaseModel):
    amount_php: Optional[float] = None
    category:   Optional[str]   = None
    description: Optional[str]  = None
    referrer:   Optional[str]   = None


class ExpenseOut(BaseModel):
    id: str
    date: str
    amount_php: float
    category: str
    description: Optional[str]
    referrer: Optional[str]
    recorded_by: str
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]


def _to_out(e: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=str(e.id),
        date=str(e.date),
        amount_php=e.amount_php,
        category=e.category,
        description=e.description,
        referrer=e.referrer,
        recorded_by=e.recorded_by,
        status=e.status,
        approved_by=e.approved_by,
        approved_at=e.approved_at.isoformat() if e.approved_at else None,
    )


@router.get("/categories")
async def get_categories():
    return EXPENSE_CATEGORIES


@router.get("/today", response_model=list[ExpenseOut])
async def get_today_expenses(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    rows = db.query(Expense).filter(Expense.date == get_today()).order_by(Expense.created_at.desc()).all()
    return [_to_out(e) for e in rows]


@router.post("/", response_model=ExpenseOut, status_code=201)
async def create_expense(
    body: ExpenseIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    if body.category not in EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {EXPENSE_CATEGORIES}")
    if body.category == "OTHERS" and not (body.description or "").strip():
        raise HTTPException(status_code=400, detail="Description is required when category is OTHERS")
    if body.category == "COMMISSION_PAYOUT" and not (body.referrer or "").strip():
        raise HTTPException(status_code=400, detail="Referrer name is required for commission payouts")
    if body.amount_php <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    expense = Expense(
        id=str(uuid.uuid4()),
        date=get_today(),
        amount_php=body.amount_php,
        category=body.category,
        description=body.description or None,
        referrer=body.referrer.strip() if body.referrer else None,
        recorded_by=current_user.username,
        status="APPROVED",
        approved_by=current_user.username,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.patch("/{expense_id}", response_model=ExpenseOut)
async def edit_expense(
    expense_id: str,
    body: ExpensePatch,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    expense = db.query(Expense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    if str(expense.date) != str(get_today()):
        raise HTTPException(status_code=403, detail="Only same-day expenses can be edited")

    if body.amount_php is not None:
        if body.amount_php <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        expense.amount_php = body.amount_php
    if body.category is not None:
        if body.category not in EXPENSE_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        expense.category = body.category
    if body.description is not None:
        expense.description = body.description or None
    if body.referrer is not None:
        expense.referrer = body.referrer.strip() or None

    if expense.category == "OTHERS" and not (expense.description or "").strip():
        raise HTTPException(status_code=400, detail="Description is required when category is OTHERS")
    if expense.category == "COMMISSION_PAYOUT" and not (expense.referrer or "").strip():
        raise HTTPException(status_code=400, detail="Referrer name is required for commission payouts")

    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.post("/{expense_id}/approve", response_model=ExpenseOut)
async def approve_expense(
    expense_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    expense = db.query(Expense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    expense.status = "APPROVED"
    expense.approved_by = current_user.username
    expense.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.post("/{expense_id}/reject", response_model=ExpenseOut)
async def reject_expense(
    expense_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    expense = db.query(Expense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    expense.status = "REJECTED"
    expense.approved_by = current_user.username
    expense.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(expense)
    return _to_out(expense)


@router.get("/commission-payouts", response_model=list[ExpenseOut])
async def get_commission_payouts(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """Commission payout expenses, optionally filtered by date range."""
    q = db.query(Expense).filter(Expense.category == "COMMISSION_PAYOUT")
    if date_from:
        q = q.filter(Expense.date >= date_from)
    if date_to:
        q = q.filter(Expense.date <= date_to)
    rows = q.order_by(Expense.date.desc(), Expense.created_at.desc()).all()
    return [_to_out(e) for e in rows]
