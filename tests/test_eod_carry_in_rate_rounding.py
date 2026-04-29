"""
EOD close MUST round next-day carry_in_rate to currency.decimal_places.

Background: prior to 2026-04-29, EOD stamped raw weighted-avg floats (e.g.
59.36119190481033 for USD) into daily_positions.carry_in_rate, which then
flowed into the next day's daily report and caused total_closing_stock_php
to drift by ₱thousands vs Ken's Excel STOCKSLEFT. The rule is: round avg to
currency.decimal_places BEFORE writing — same rule that governs THAN.

This test pins the rule by constructing a BUY pattern that produces a non-
terminating weighted average and asserting the stored carry_in_rate has no
more decimals than the currency allows.
"""
from datetime import timedelta

import pytest
from app.core.today import get_today
from app.models.currency import Currency, CurrencyCategory, DailyPosition, DailyRate
from app.models.transaction import (
    PaymentMode, PaymentStatus, Transaction, TxnSource, TxnType,
)
from tests.conftest import auth_header


def _decimals(value: float) -> int:
    """Count significant decimal places in a float (ignores trailing zeros)."""
    s = repr(value)
    if "." not in s:
        return 0
    return len(s.split(".")[1].rstrip("0"))


@pytest.fixture
def usd_jpy_setup(db):
    today = get_today()
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(Currency(
        code="JPY", name="Japanese Yen", flag="🇯🇵",
        category=CurrencyCategory.MAIN, decimal_places=4, sort_order=2, is_active="Y",
    ))
    db.add(DailyRate(date=today, currency_code="USD", buy_rate=59.0, sell_rate=60.0, set_by="admintest"))
    db.add(DailyRate(date=today, currency_code="JPY", buy_rate=0.37, sell_rate=0.40, set_by="admintest"))
    db.add(DailyPosition(date=today, currency_code="USD", carry_in_qty=10_000.0, carry_in_rate=59.55))
    db.add(DailyPosition(date=today, currency_code="JPY", carry_in_qty=1_500_000.0, carry_in_rate=0.3704))
    db.commit()


def _add_buy(db, *, code: str, qty: float, rate: float, suffix: str):
    db.add(Transaction(
        id=f"OR-EODT-{suffix}",
        date=get_today(),
        time="10:00 AM",
        type=TxnType.BUY,
        source=TxnSource.COUNTER,
        currency_code=code,
        foreign_amt=qty,
        rate=rate,
        php_amt=round(qty * rate, 2),
        than=0,
        daily_avg_cost=rate,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH,
        payment_status=PaymentStatus.RECEIVED,
    ))


class TestEODCarryInRateRounding:
    def test_carry_in_rate_rounded_to_currency_decimal_places(
        self, client, admin_user, cashier_user, usd_jpy_setup, db
    ):
        # BUYs designed so weighted avg has many decimals.
        # USD: carry 10000@59.55 + 7@59 + 13@58 → avg = 59.5474... (well past 2dp)
        _add_buy(db, code="USD", qty=7,  rate=59.0, suffix="U1")
        _add_buy(db, code="USD", qty=13, rate=58.0, suffix="U2")
        # JPY: carry 1.5M@0.3704 + 1@0.37 + 2@0.36 → avg = 0.3703996... (past 4dp)
        _add_buy(db, code="JPY", qty=1, rate=0.37, suffix="J1")
        _add_buy(db, code="JPY", qty=2, rate=0.36, suffix="J2")
        db.commit()

        r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text

        tomorrow = get_today() + timedelta(days=1)
        positions = {
            p.currency_code: p
            for p in db.query(DailyPosition).filter_by(date=tomorrow).all()
        }

        usd_dp = _decimals(positions["USD"].carry_in_rate)
        jpy_dp = _decimals(positions["JPY"].carry_in_rate)
        assert usd_dp <= 2, f"USD carry_in_rate has {usd_dp} decimals: {positions['USD'].carry_in_rate}"
        assert jpy_dp <= 4, f"JPY carry_in_rate has {jpy_dp} decimals: {positions['JPY'].carry_in_rate}"

    def test_no_buys_carry_in_rate_still_clean(
        self, client, admin_user, cashier_user, usd_jpy_setup, db
    ):
        # No BUYs today → tomorrow's carry-in rate = today's carry-in rate (already clean).
        r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text

        tomorrow = get_today() + timedelta(days=1)
        usd_pos = db.query(DailyPosition).filter_by(date=tomorrow, currency_code="USD").first()
        assert usd_pos.carry_in_rate == pytest.approx(59.55)
        assert _decimals(usd_pos.carry_in_rate) <= 2
