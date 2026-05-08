from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.today import get_today
from app.models.currency import DailyRate, DailyPosition, Currency
from app.schemas.forex import CurrencyRateIn
from app.api.v1.auth import require_role, TokenData
from datetime import date

router = APIRouter(prefix="/rates", tags=["rates"])


@router.get("/public")
async def get_public_rates(db: Session = Depends(get_db)):
    """Public endpoint — no auth required. Returns today's rates for display."""
    today = get_today()
    currencies = {c.code: c for c in db.query(Currency).filter_by(is_active="Y").order_by(Currency.sort_order).all()}
    rates = db.query(DailyRate).filter_by(date=today).all()
    return [
        {
            "currency_code": r.currency_code,
            "name": currencies[r.currency_code].name if r.currency_code in currencies else "",
            "flag": currencies[r.currency_code].flag if r.currency_code in currencies else "",
            "decimal_places": currencies[r.currency_code].decimal_places if r.currency_code in currencies else 4,
            "buy_rate": r.buy_rate,
            "sell_rate": r.sell_rate,
        }
        for r in rates
        if r.currency_code in currencies
    ]


@router.get("/today")
async def get_today_rates(
    current_user: TokenData = Depends(require_role("admin", "cashier")),
    db: Session = Depends(get_db),
):
    today = get_today()
    rates = db.query(DailyRate).filter_by(date=today).all()
    return [
        {
            "currency_code": r.currency_code,
            "buy_rate": r.buy_rate,
            "sell_rate": r.sell_rate,
            "set_by": r.set_by,
        }
        for r in rates
    ]


@router.post("/today", status_code=status.HTTP_201_CREATED)
async def set_today_rates(
    rates: List[CurrencyRateIn],
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """
    Set or update today's exchange rates. Admin or supervisor (treasurer).
    If a rate already exists for today it is updated, otherwise inserted.
    """
    today = get_today()

    # Validate all currency codes exist
    valid_codes = {c.code for c in db.query(Currency).all()}
    invalid = [r.code for r in rates if r.code not in valid_codes]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown currency codes: {invalid}",
        )

    upserted = 0
    for r in rates:
        existing = db.query(DailyRate).filter_by(date=today, currency_code=r.code).first()
        if existing:
            existing.buy_rate = r.buy_rate
            existing.sell_rate = r.sell_rate
            existing.set_by = current_user.username
        else:
            db.add(DailyRate(
                date=today,
                currency_code=r.code,
                buy_rate=r.buy_rate,
                sell_rate=r.sell_rate,
                set_by=current_user.username,
            ))
        upserted += 1

    db.commit()
    return {"message": f"{upserted} rates saved for {today}", "by": current_user.username}


@router.post("/from-carry-in", status_code=status.HTTP_201_CREATED)
async def set_rates_from_carry_in(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """Copy today's carry-in rates into DailyRate. Admin or supervisor (treasurer)."""
    today = get_today()
    positions = db.query(DailyPosition).filter_by(date=today).all()
    if not positions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No carry-in positions found for today. Set opening positions first.",
        )

    upserted = 0
    for pos in positions:
        rate = pos.carry_in_rate or 0
        existing = db.query(DailyRate).filter_by(date=today, currency_code=pos.currency_code).first()
        if existing:
            existing.buy_rate  = rate
            existing.sell_rate = rate
            existing.set_by    = current_user.username
        else:
            db.add(DailyRate(
                date=today,
                currency_code=pos.currency_code,
                buy_rate=rate,
                sell_rate=rate,
                set_by=current_user.username,
            ))
        upserted += 1

    db.commit()
    return {"message": f"{upserted} rates copied from carry-in for {today}", "by": current_user.username}
