"""
EOD close MUST re-stamp THAN on today's SELLs using the full-day weighted-
average cost.

Background: when a SELL is inserted, daily_avg_cost is computed against the
BUYs that exist at that moment. If BUYs arrive AFTER (rider entries, edit-
request approvals, backdated entries), the SELL's THAN goes stale. Pre-bake-
in we ran scripts/recompute_than.py manually after each reconciliation. EOD
close now does this automatically.
"""
from datetime import timedelta

import pytest
from app.core.today import get_today
from app.models.currency import Currency, CurrencyCategory, DailyPosition, DailyRate
from app.models.transaction import (
    PaymentMode, PaymentStatus, Transaction, TxnSource, TxnType,
)
from tests.conftest import auth_header


@pytest.fixture
def usd_setup(db):
    today = get_today()
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(DailyRate(date=today, currency_code="USD", buy_rate=59.0, sell_rate=61.0, set_by="admintest"))
    db.add(DailyPosition(date=today, currency_code="USD", carry_in_qty=100.0, carry_in_rate=60.00))
    db.commit()


def test_eod_recomputes_than_for_late_arriving_buys(
    client, admin_user, cashier_user, usd_setup, db
):
    today = get_today()

    # SELL stamped FIRST against a stale partial-day cost (60.00 = carry only).
    # qty 50 @ 61 → THAN = 50 × (61 − 60) = 50.00
    db.add(Transaction(
        id="OR-RT-S1", date=today, time="09:00 AM",
        type=TxnType.SELL, source=TxnSource.COUNTER, currency_code="USD",
        foreign_amt=50.0, rate=61.0, php_amt=3050.0,
        than=50.00, daily_avg_cost=60.00,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH, payment_status=PaymentStatus.RECEIVED,
    ))
    # BUY arrives LATER (e.g. backdated rider entry) — pulls weighted avg up.
    # 100 @ 60 + 200 @ 58 → avg = (6000 + 11600)/300 = 58.6666... → 58.67
    db.add(Transaction(
        id="OR-RT-B1", date=today, time="11:00 AM",
        type=TxnType.BUY, source=TxnSource.COUNTER, currency_code="USD",
        foreign_amt=200.0, rate=58.0, php_amt=11600.0,
        than=0, daily_avg_cost=58.0,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH, payment_status=PaymentStatus.RECEIVED,
    ))
    db.commit()

    r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
    assert r.status_code == 200, r.text

    sell = db.query(Transaction).filter_by(id="OR-RT-S1").first()
    db.refresh(sell)
    assert sell.daily_avg_cost == pytest.approx(58.67), \
        f"daily_avg_cost not refreshed: {sell.daily_avg_cost}"
    expected_than = round((61.0 - 58.67) * 50.0, 2)  # 116.50
    assert sell.than == pytest.approx(expected_than), \
        f"THAN not recomputed: got {sell.than}, expected {expected_than}"


def test_eod_recompute_handles_negative_than(
    client, admin_user, cashier_user, usd_setup, db
):
    today = get_today()
    # Loss case: sell rate < cost. carry 100@60 → daily_avg 60.
    # SELL 50 @ 58 → THAN = 50 × (58 − 60) = −100.
    db.add(Transaction(
        id="OR-RT-S2", date=today, time="10:00 AM",
        type=TxnType.SELL, source=TxnSource.COUNTER, currency_code="USD",
        foreign_amt=50.0, rate=58.0, php_amt=2900.0,
        than=0,  # not yet stamped — EOD must compute
        daily_avg_cost=0.0,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH, payment_status=PaymentStatus.RECEIVED,
    ))
    db.commit()

    r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
    assert r.status_code == 200, r.text

    sell = db.query(Transaction).filter_by(id="OR-RT-S2").first()
    db.refresh(sell)
    assert sell.daily_avg_cost == pytest.approx(60.00)
    assert sell.than == pytest.approx(-100.00), \
        f"Negative THAN not stamped: {sell.than}"


def test_eod_recompute_is_idempotent(
    client, admin_user, cashier_user, usd_setup, db
):
    today = get_today()
    db.add(Transaction(
        id="OR-RT-S3", date=today, time="10:00 AM",
        type=TxnType.SELL, source=TxnSource.COUNTER, currency_code="USD",
        foreign_amt=10.0, rate=61.0, php_amt=610.0,
        than=10.00, daily_avg_cost=60.00,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH, payment_status=PaymentStatus.RECEIVED,
    ))
    db.commit()

    r1 = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
    assert r1.status_code == 200
    r2 = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
    assert r2.status_code == 200

    sell = db.query(Transaction).filter_by(id="OR-RT-S3").first()
    db.refresh(sell)
    assert sell.daily_avg_cost == pytest.approx(60.00)
    assert sell.than == pytest.approx(10.00)
