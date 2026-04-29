from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta

from app.core.database import get_db
from app.models.currency import Currency, DailyRate, DailyPosition
from app.models.transaction import Transaction, TxnSource, TxnType, RiderDispatch, DispatchStatus, PaymentStatus
from app.models.shift import TellerShift, ShiftStatus
from app.models.user import User
from app.schemas.forex import DashboardSummaryOut, CurrencyPositionOut, TransactionOut, CapitalTrendPoint
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import get_current_user, TokenData
from app.core.today import get_today

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ── Simple 30-second in-memory cache ─────────────────────────────────────────
_cache: dict = {}
_CACHE_TTL = 30  # seconds


def _cache_key(today: date) -> str:
    return f"dashboard:{today}"


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry and (datetime.utcnow() - entry["ts"]).total_seconds() < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cached(key: str, data) -> None:
    _cache[key] = {"ts": datetime.utcnow(), "data": data}


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=DashboardSummaryOut)
async def get_dashboard_summary(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = get_today()
    cache_key = _cache_key(today)

    cached = _get_cached(cache_key)
    if cached:
        return cached

    # 1. All active currencies
    currencies = db.query(Currency).filter_by(is_active="Y").all()

    # 2. Today's rates (keyed by currency code)
    rates = {
        r.currency_code: r
        for r in db.query(DailyRate).filter_by(date=today).all()
    }

    # 3. Today's opening positions / carry-ins
    positions_map = {
        p.currency_code: p
        for p in db.query(DailyPosition).filter_by(date=today).all()
    }

    # 4. Exclude demo accounts from all calculations
    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()

    # 5. All buys + excess today — used for position computation
    # EXCESS entries (rate=0, php=0) add to stock without affecting PHP totals
    buys_today = (
        db.query(Transaction)
        .filter(Transaction.date == today, Transaction.type.in_(["BUY", "EXCESS"]))
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )
    buys_by_currency: dict[str, list[Transaction]] = {}
    for t in buys_today:
        buys_by_currency.setdefault(t.currency_code, []).append(t)

    # 6. Aggregate totals — EXCESS excluded from PHP totals (no money changed hands)
    sells_today = (
        db.query(Transaction)
        .filter(Transaction.date == today, Transaction.type == "SELL")
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )
    # PENDING transactions are listed but excluded from financial totals — money
    # hasn't actually changed hands until the customer pays.
    received = lambda t: t.payment_status != PaymentStatus.PENDING
    total_than   = sum(t.than    for t in sells_today if received(t))
    total_bought = sum(t.php_amt for t in buys_today  if t.type == "BUY" and received(t))
    total_sold   = sum(t.php_amt for t in sells_today if received(t))

    # 7. Compute positions for currencies that have a rate set today
    computed_positions: list[CurrencyPositionOut] = []
    for curr in currencies:
        rate_row = rates.get(curr.code)
        if not rate_row:
            continue

        pos_row = positions_map.get(curr.code)
        carry_in = CarryIn(
            qty=pos_row.carry_in_qty if pos_row else 0,
            rate=pos_row.carry_in_rate if pos_row else rate_row.buy_rate,
        )
        today_buys = [
            TodayBuy(qty=t.foreign_amt, rate=t.rate)
            for t in buys_by_currency.get(curr.code, [])
        ]

        result = compute_position(carry_in, today_buys, rate_row.sell_rate)

        computed_positions.append(CurrencyPositionOut(
            code=curr.code,
            name=curr.name,
            flag=curr.flag or "",
            category=curr.category.value,
            decimal_places=curr.decimal_places,
            today_buy_rate=rate_row.buy_rate,
            total_qty=result.total_qty,
            daily_avg_cost=result.daily_avg_cost,
            today_sell_rate=rate_row.sell_rate,
            stock_value_php=result.stock_value_php,
            today_gain_per_unit=result.today_gain_per_unit,
            unrealized_php=result.unrealized_php,
        ))

    # 8. Recent transactions — display only, limited to 20
    recent_txns = (
        db.query(Transaction)
        .filter(Transaction.date == today)
        .filter(~Transaction.cashier.in_(demo_users))
        .order_by(Transaction.created_at.desc())
        .limit(20)
        .all()
    )
    recent_out = [
        TransactionOut(
            id=t.id, time=t.time, type=t.type, source=t.source,
            currency=t.currency_code, foreign_amt=t.foreign_amt,
            rate=t.rate, php_amt=t.php_amt, than=t.than,
            cashier=t.cashier, customer=t.customer,
            payment_status=t.payment_status.value if hasattr(t.payment_status, 'value') else (t.payment_status or "RECEIVED"),
        )
        for t in recent_txns
    ]

    total_stock = sum(p.stock_value_php for p in computed_positions)

    # 9. PHP Cash — sum across all cashier shifts + active rider dispatches
    shifts_today = (
        db.query(TellerShift)
        .filter(TellerShift.date == today)
        .filter(~TellerShift.cashier.in_(demo_users))
        .all()
    )

    # Index counter transactions by cashier for O(1) shift lookup
    counter_by_cashier: dict[str, list[Transaction]] = {}
    for t in buys_today + sells_today:
        if t.source == TxnSource.COUNTER:
            counter_by_cashier.setdefault(t.cashier, []).append(t)

    php_cash = 0.0
    for shift in shifts_today:
        if shift.status == ShiftStatus.CLOSED and shift.closing_cash_php is not None:
            # Use actual counted cash for closed shifts
            php_cash += shift.closing_cash_php
        else:
            # Open shift: opening + SELLs - BUYs + replenishments
            txns = counter_by_cashier.get(shift.cashier, [])
            sell_php = sum(t.php_amt for t in txns if t.type == TxnType.SELL and received(t))
            buy_php  = sum(t.php_amt for t in txns if t.type == TxnType.BUY  and received(t))
            replen   = sum(r.amount_php for r in shift.replenishments)
            php_cash += shift.opening_cash_php + sell_php - buy_php + replen

    # Active riders in the field: their starting cash + SELL - BUY
    active_dispatches = (
        db.query(RiderDispatch)
        .filter(RiderDispatch.date == today, RiderDispatch.status == DispatchStatus.IN_FIELD)
        .all()
    )
    rider_by_username: dict[str, list[Transaction]] = {}
    for t in buys_today + sells_today:
        if t.source == TxnSource.RIDER:
            rider_by_username.setdefault(t.cashier, []).append(t)

    for dispatch in active_dispatches:
        txns     = rider_by_username.get(dispatch.rider_username, [])
        sell_php = sum(t.php_amt for t in txns if t.type == TxnType.SELL and received(t))
        buy_php  = sum(t.php_amt for t in txns if t.type == TxnType.BUY  and received(t))
        php_cash += dispatch.cash_php + sell_php - buy_php

    opening_capital = php_cash + total_stock

    # 10. Capital trend — last 14 days of stock value from daily_positions + today live
    trend_start = today - timedelta(days=13)
    trend_rows = (
        db.query(
            DailyPosition.date,
            func.sum(DailyPosition.carry_in_qty * DailyPosition.carry_in_rate).label('stock_val')
        )
        .filter(DailyPosition.date >= trend_start, DailyPosition.date < today)
        .group_by(DailyPosition.date)
        .order_by(DailyPosition.date)
        .all()
    )
    capital_trend = [
        CapitalTrendPoint(date=row.date.strftime('%b %d'), value=round(row.stock_val or 0, 0))
        for row in trend_rows
    ]
    # Append today's live value
    capital_trend.append(CapitalTrendPoint(date=today.strftime('%b %d'), value=round(total_stock + php_cash, 0)))

    result_out = DashboardSummaryOut(
        date=today,
        opening_capital=opening_capital,
        php_cash=round(php_cash, 2),
        total_stock_value=total_stock,
        total_capital=round(php_cash + total_stock, 2),
        total_unrealized=sum(p.unrealized_php for p in computed_positions),
        total_than_today=total_than,
        total_bought_today=total_bought,
        total_sold_today=total_sold,
        positions=computed_positions,
        recent_transactions=recent_out,
        capital_trend=capital_trend,
    )

    _set_cached(cache_key, result_out)
    return result_out
