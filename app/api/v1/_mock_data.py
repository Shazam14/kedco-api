# ─────────────────────────────────────────────
# Temporary mock data — mirrors data.ts exactly.
# This lets the frontend work immediately while
# we wire up the real database.
# Delete this file once DB is connected.
# ─────────────────────────────────────────────

from datetime import date
from app.schemas.forex import DashboardSummaryOut, CurrencyPositionOut, TransactionOut
from app.services.forex import compute_position, CarryIn, TodayBuy


def _build_position(code, name, flag, category, carry_qty, carry_rate,
                    buys, sell_rate, decimal_places=4) -> CurrencyPositionOut:
    result = compute_position(
        CarryIn(qty=carry_qty, rate=carry_rate),
        [TodayBuy(qty=q, rate=r) for q, r in buys],
        sell_rate,
    )
    return CurrencyPositionOut(
        code=code, name=name, flag=flag, category=category,
        decimal_places=decimal_places,
        today_buy_rate=carry_rate,
        total_qty=result.total_qty,
        daily_avg_cost=result.daily_avg_cost,
        today_sell_rate=sell_rate,
        stock_value_php=result.stock_value_php,
        today_gain_per_unit=result.today_gain_per_unit,
        unrealized_php=result.unrealized_php,
    )


def get_mock_summary() -> DashboardSummaryOut:
    positions = [
        _build_position("USD", "US Dollar", "🇺🇸", "MAIN",
                        1200, 57.80, [(300, 57.50), (350, 57.60)], 58.05),
        _build_position("JPY", "Japanese Yen", "🇯🇵", "MAIN",
                        180000, 0.2950, [(50000, 0.2920), (50000, 0.2930)], 0.3000),
        _build_position("KRW", "Korean Won", "🇰🇷", "MAIN",
                        350000, 0.0355, [(100000, 0.0352)], 0.0360),
        _build_position("EUR", "Euro", "🇪🇺", "2ND",
                        170, 54.50, [(150, 54.20)], 55.00),
        _build_position("GBP", "British Pound", "🇬🇧", "2ND",
                        120, 63.00, [(60, 62.80)], 63.50),
        _build_position("SGD", "Singapore Dollar", "🇸🇬", "2ND",
                        240, 36.20, [(300, 36.00)], 36.50),
    ]

    usd_avg = next(p.daily_avg_cost for p in positions if p.code == "USD")
    jpy_avg = next(p.daily_avg_cost for p in positions if p.code == "JPY")
    gbp_avg = next(p.daily_avg_cost for p in positions if p.code == "GBP")

    transactions = [
        TransactionOut(id="OR-00080412", time="06:58 PM", type="BUY", source="COUNTER",
                       currency="EUR", foreign_amt=150, rate=54.20, php_amt=8130,
                       than=0, cashier="ADP28", customer="Walk-in"),
        TransactionOut(id="OR-00080411", time="06:43 PM", type="BUY", source="COUNTER",
                       currency="USD", foreign_amt=100, rate=57.60, php_amt=5760,
                       than=0, cashier="ADP28"),
        TransactionOut(id="RD-00000312", time="06:15 PM", type="SELL", source="RIDER",
                       currency="JPY", foreign_amt=50000, rate=0.3000, php_amt=15000,
                       than=round((0.3000 - jpy_avg) * 50000, 2),
                       cashier="JUN", customer="Hotel Okura"),
        TransactionOut(id="OR-00080410", time="06:02 PM", type="SELL", source="COUNTER",
                       currency="GBP", foreign_amt=200, rate=63.50, php_amt=12700,
                       than=round((63.50 - gbp_avg) * 200, 2),
                       cashier="ADP28", customer="Bravada Travel"),
        TransactionOut(id="OR-00080408", time="04:12 PM", type="SELL", source="COUNTER",
                       currency="USD", foreign_amt=200, rate=58.05, php_amt=11610,
                       than=round((58.05 - usd_avg) * 200, 2),
                       cashier="ADP28", customer="Cebu Pacific Agent"),
    ]

    total_stock = sum(p.stock_value_php for p in positions)
    php_cash = 359_600
    opening_capital = 1_000_000

    return DashboardSummaryOut(
        date=date.today(),
        opening_capital=opening_capital,
        php_cash=php_cash,
        total_stock_value=total_stock,
        total_capital=php_cash + total_stock,
        total_unrealized=sum(p.unrealized_php for p in positions),
        total_than_today=sum(t.than for t in transactions if t.type == "SELL"),
        total_bought_today=sum(t.php_amt for t in transactions if t.type == "BUY"),
        total_sold_today=sum(t.php_amt for t in transactions if t.type == "SELL"),
        positions=positions,
        recent_transactions=transactions,
    )
