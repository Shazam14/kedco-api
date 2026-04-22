from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import timedelta, date

from app.core.database import get_db
from app.models.currency import DailyRate, DailyPosition
from app.models.transaction import Transaction, DailySummary
from app.models.user import User
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import require_role, TokenData
from app.core.today import get_today

router = APIRouter(prefix="/eod", tags=["end-of-day"])

OPENING_CAPITAL = 0  # TODO: move to DB config — set by admin on first use


@router.post("/close")
async def close_day(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    End of Day close:
    1. Calculate remaining stock per currency (carry-in + bought - sold)
    2. Write tomorrow's daily_positions using today's closing sell rate
    3. Save today's DailySummary (P&L snapshot)

    Idempotent — safe to run again if interrupted.
    """
    today    = get_today()
    tomorrow = today + timedelta(days=1)

    # ── 1. Get today's rates ──────────────────────────────────────────
    rates_today = {
        r.currency_code: r
        for r in db.query(DailyRate).filter_by(date=today).all()
    }
    if not rates_today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rates set for today. Cannot close day.",
        )

    # ── 2. Get today's opening positions ─────────────────────────────
    positions_today = {
        p.currency_code: p
        for p in db.query(DailyPosition).filter_by(date=today).all()
    }

    # ── 3. Get today's transactions per currency (exclude demo accounts) ─
    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()
    txns_today = (
        db.query(Transaction)
        .filter(Transaction.date == today)
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )

    bought_by_currency: dict[str, list[Transaction]] = {}
    sold_by_currency:   dict[str, list[Transaction]] = {}
    for t in txns_today:
        if t.type == "BUY":
            bought_by_currency.setdefault(t.currency_code, []).append(t)
        else:
            sold_by_currency.setdefault(t.currency_code, []).append(t)

    # ── 4. Compute carry-forward for each currency ────────────────────
    carry_forward = []
    total_stock_value = 0.0
    total_unrealized  = 0.0

    for code, rate_row in rates_today.items():
        pos_row  = positions_today.get(code)
        carry_in = CarryIn(
            qty  = pos_row.carry_in_qty  if pos_row else 0,
            rate = pos_row.carry_in_rate if pos_row else rate_row.buy_rate,
        )
        today_buys = [TodayBuy(qty=t.foreign_amt, rate=t.rate)
                      for t in bought_by_currency.get(code, [])]
        total_sold_qty = sum(t.foreign_amt for t in sold_by_currency.get(code, []))

        result       = compute_position(carry_in, today_buys, rate_row.sell_rate)
        remaining_qty = result.total_qty - total_sold_qty

        total_stock_value += max(remaining_qty, 0) * rate_row.sell_rate
        total_unrealized  += result.unrealized_php

        carry_forward.append({
            "currency_code":  code,
            "carry_in_qty":   max(remaining_qty, 0),
            "carry_in_rate":  result.daily_avg_cost,  # tomorrow's cost basis = today's closing avg rate (confirmed by Ken 2026-04-13)
        })

    # ── 5. Write tomorrow's positions (upsert) ────────────────────────
    for cf in carry_forward:
        existing = db.query(DailyPosition).filter_by(
            date=tomorrow, currency_code=cf["currency_code"]
        ).first()
        if existing:
            existing.carry_in_qty  = cf["carry_in_qty"]
            existing.carry_in_rate = cf["carry_in_rate"]
        else:
            db.add(DailyPosition(
                date          = tomorrow,
                currency_code = cf["currency_code"],
                carry_in_qty  = cf["carry_in_qty"],
                carry_in_rate = cf["carry_in_rate"],
            ))

    # ── 6. Save today's DailySummary (upsert) ─────────────────────────
    total_than   = sum(t.than    for t in txns_today if t.type == "SELL")
    total_bought = sum(t.php_amt for t in txns_today if t.type == "BUY")
    total_sold   = sum(t.php_amt for t in txns_today if t.type == "SELL")
    php_cash     = OPENING_CAPITAL + total_sold - total_bought

    summary = db.query(DailySummary).filter_by(date=today).first()
    if summary:
        summary.total_stock_value = total_stock_value
        summary.total_capital     = php_cash + total_stock_value
        summary.total_than        = total_than
        summary.total_bought      = total_bought
        summary.total_sold        = total_sold
        summary.php_cash          = php_cash
        summary.closed_by         = current_user.username
    else:
        db.add(DailySummary(
            date              = today,
            opening_capital   = OPENING_CAPITAL,
            php_cash          = php_cash,
            total_stock_value = total_stock_value,
            total_capital     = php_cash + total_stock_value,
            total_than        = total_than,
            total_bought      = total_bought,
            total_sold        = total_sold,
            closed_by         = current_user.username,
        ))

    db.commit()

    return {
        "closed_date":      str(today),
        "currencies_rolled": len(carry_forward),
        "tomorrow_ready":   str(tomorrow),
        "total_than":       round(total_than, 2),
        "total_bought":     round(total_bought, 2),
        "total_sold":       round(total_sold, 2),
        "closing_capital":  round(php_cash + total_stock_value, 2),
        "closed_by":        current_user.username,
        "message": f"Day closed. {len(carry_forward)} currencies rolled to {tomorrow}.",
    }


@router.get("/summary/{day}")
async def get_day_summary(
    day: date,
    current_user: TokenData = Depends(require_role("admin", "cashier")),
    db: Session = Depends(get_db),
):
    """Retrieve a saved EOD summary for any past date."""
    summary = db.query(DailySummary).filter_by(date=day).first()
    if not summary:
        raise HTTPException(status_code=404, detail=f"No summary found for {day}")
    return {
        "date":             str(summary.date),
        "opening_capital":  summary.opening_capital,
        "php_cash":         summary.php_cash,
        "total_stock_value":summary.total_stock_value,
        "total_capital":    summary.total_capital,
        "total_than":       summary.total_than,
        "total_bought":     summary.total_bought,
        "total_sold":       summary.total_sold,
        "closed_by":        summary.closed_by,
    }
