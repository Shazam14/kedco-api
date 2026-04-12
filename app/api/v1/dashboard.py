from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date

from app.core.database import get_db
from app.models.currency import Currency, DailyRate, DailyPosition
from app.models.transaction import Transaction
from app.schemas.forex import DashboardSummaryOut, CurrencyPositionOut, TransactionOut
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import get_current_user, TokenData

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

OPENING_CAPITAL = 1_000_000  # TODO: move to DB config table


@router.get("/summary", response_model=DashboardSummaryOut)
async def get_dashboard_summary(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()

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

    # 4. All buys today (for weighted avg calculation)
    buys_today = db.query(Transaction).filter_by(date=today, type="BUY").all()
    buys_by_currency: dict[str, list[Transaction]] = {}
    for t in buys_today:
        buys_by_currency.setdefault(t.currency_code, []).append(t)

    # 5. Compute positions for currencies that have a rate set today
    computed_positions: list[CurrencyPositionOut] = []
    for curr in currencies:
        rate_row = rates.get(curr.code)
        if not rate_row:
            continue  # skip currencies with no rate set today

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

    # 6. Recent transactions (last 20)
    recent_txns = (
        db.query(Transaction)
        .filter_by(date=today)
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
        )
        for t in recent_txns
    ]

    # 7. Aggregates
    total_stock = sum(p.stock_value_php for p in computed_positions)
    php_cash = OPENING_CAPITAL  # TODO: track actual cash movements
    total_than = sum(t.than for t in recent_txns if t.type == "SELL")
    total_bought = sum(t.php_amt for t in recent_txns if t.type == "BUY")
    total_sold = sum(t.php_amt for t in recent_txns if t.type == "SELL")

    return DashboardSummaryOut(
        date=today,
        opening_capital=OPENING_CAPITAL,
        php_cash=php_cash,
        total_stock_value=total_stock,
        total_capital=php_cash + total_stock,
        total_unrealized=sum(p.unrealized_php for p in computed_positions),
        total_than_today=total_than,
        total_bought_today=total_bought,
        total_sold_today=total_sold,
        positions=computed_positions,
        recent_transactions=recent_out,
    )
