from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.core.database import get_db
from app.core.today import get_today
from app.models.currency import Currency, DailyPosition, DailyRate
from app.api.v1.auth import require_role, TokenData
from datetime import date

router = APIRouter(prefix="/positions", tags=["positions"])


class PositionIn(BaseModel):
    currency_code: str
    carry_in_qty:  float
    carry_in_rate: float


@router.get("/today")
async def get_today_positions(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    """Return today's opening positions for all active currencies."""
    today = get_today()

    currencies = db.query(Currency).filter_by(is_active="Y").order_by(Currency.sort_order).all()
    positions  = {
        p.currency_code: p
        for p in db.query(DailyPosition).filter_by(date=today).all()
    }
    rates = {
        r.currency_code: r
        for r in db.query(DailyRate).filter_by(date=today).all()
    }

    return [
        {
            "code":          c.code,
            "name":          c.name,
            "flag":          c.flag,
            "category":      c.category.value,
            "decimal_places": c.decimal_places,
            "carry_in_qty":   positions[c.code].carry_in_qty  if c.code in positions else 0,
            "carry_in_rate":  positions[c.code].carry_in_rate if c.code in positions else (
                              rates[c.code].sell_rate         if c.code in rates     else 0),
            "position_set":  c.code in positions,
        }
        for c in currencies
    ]


@router.post("/today")
async def set_today_positions(
    payload: List[PositionIn],
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Upsert opening positions for today (first-day setup or manual override)."""
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No positions provided.",
        )

    today = get_today()
    saved = 0

    for item in payload:
        existing = db.query(DailyPosition).filter_by(
            date=today, currency_code=item.currency_code
        ).first()
        if existing:
            existing.carry_in_qty  = item.carry_in_qty
            existing.carry_in_rate = item.carry_in_rate
        else:
            db.add(DailyPosition(
                date          = today,
                currency_code = item.currency_code,
                carry_in_qty  = item.carry_in_qty,
                carry_in_rate = item.carry_in_rate,
            ))
        saved += 1

    db.commit()
    return {"message": f"{saved} positions saved for {today}.", "date": str(today), "saved": saved}
