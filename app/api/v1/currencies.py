from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.today import get_today
from app.models.currency import Currency, DailyRate
from app.api.v1.auth import require_role, TokenData
from datetime import date

router = APIRouter(prefix="/currencies", tags=["currencies"])


@router.get("/")
async def list_currencies(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    """All active currencies with today's rates if already set."""
    today = get_today()
    currencies = db.query(Currency).filter_by(is_active="Y").order_by(Currency.sort_order).all()
    rates_today = {
        r.currency_code: r
        for r in db.query(DailyRate).filter_by(date=today).all()
    }

    return [
        {
            "code": c.code,
            "name": c.name,
            "flag": c.flag,
            "category": c.category.value,
            "decimal_places": c.decimal_places,
            "today_buy_rate":  rates_today[c.code].buy_rate  if c.code in rates_today else None,
            "today_sell_rate": rates_today[c.code].sell_rate if c.code in rates_today else None,
            "rate_set": c.code in rates_today,
        }
        for c in currencies
    ]
