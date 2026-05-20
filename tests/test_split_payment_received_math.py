"""
Regression: 2026-05-18 RD-7CFB1A58 — a rider SELL ₱60,760 split as
₱10,760 CASH (RECEIVED) + ₱50,000 CHEQUE (PENDING) had parent payment_status
stamped PENDING, and downstream consumers filtering on parent status dropped
the whole txn from money math. The cash portion physically in the rider's
hand was invisible to the carry/balance/drawer formulas.

The fix routes every money sum through app.services.payments.received_php
(slice-aware). This test pins the behavior end-to-end across the three
endpoints that touch the rider's drawer math: dashboard, daily report,
and treasurer shift summary.
"""
from tests.conftest import auth_header


def _make_split_sell(client, rider_user, make_dispatch, usd_setup):
    make_dispatch()
    r = client.post(
        "/api/v1/transactions/",
        headers=auth_header("ridertest", "rider"),
        json={
            "type": "SELL", "source": "RIDER", "currency": "USD",
            "foreign_amt": 1000, "rate": 58.0, "cashier": "ridertest",
            "payments": [
                {"method": "CASH",   "amount_php": 10760.0, "status": "RECEIVED"},
                {"method": "CHEQUE", "amount_php": 47240.0, "status": "PENDING"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    # Parent rolls up to PENDING (any-pending rule). Cash slice is RECEIVED.
    assert r.json()["payment_status"] == "PENDING"
    return r.json()


import pytest


@pytest.fixture
def usd_setup(db):
    from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition
    from app.core.today import get_today
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(DailyRate(
        date=get_today(), currency_code="USD",
        buy_rate=57.0, sell_rate=58.0, set_by="admintest",
    ))
    db.add(DailyPosition(
        date=get_today(), currency_code="USD",
        carry_in_qty=10_000.0, carry_in_rate=57.5,
    ))
    db.commit()


class TestSliceReceivedMath:
    def test_received_helper_returns_cash_slice_only(self, client, db, rider_user, make_dispatch, usd_setup):
        from app.services.payments import received_php, pending_php, received_share
        from app.models.transaction import Transaction

        body = _make_split_sell(client, rider_user, make_dispatch, usd_setup)
        t = db.query(Transaction).filter_by(id=body["id"]).first()

        # Cash slice in hand right now = ₱10,760. Cheque slice pending = ₱47,240.
        assert received_php(t) == 10760.0
        assert pending_php(t) == 47240.0
        assert round(received_share(t), 6) == round(10760.0 / 58000.0, 6)

    def test_dashboard_total_sold_includes_cash_leg(self, client, admin_user, rider_user, make_dispatch, usd_setup):
        _make_split_sell(client, rider_user, make_dispatch, usd_setup)
        r = client.get("/api/v1/dashboard/summary", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        # ₱10,760 cash leg must surface in total_sold even though parent is PENDING.
        assert r.json()["total_sold_today"] >= 10760.0

    def test_daily_report_per_cashier_sees_cash_leg(self, client, admin_user, rider_user, make_dispatch, usd_setup):
        _make_split_sell(client, rider_user, make_dispatch, usd_setup)
        r = client.get("/api/v1/report/daily", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        rider_row = next((c for c in r.json()["by_cashier"] if c["cashier"] == "ridertest"), None)
        assert rider_row is not None, "rider should appear with cash-leg volume"
        assert rider_row["sell_php"] >= 10760.0

    def test_eod_total_sold_includes_cash_leg(self, client, db, admin_user, rider_user, make_dispatch, usd_setup):
        from app.models.transaction import DailySummary
        from app.core.today import get_today

        _make_split_sell(client, rider_user, make_dispatch, usd_setup)
        r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        summary = db.query(DailySummary).filter_by(date=get_today()).first()
        assert summary is not None
        assert summary.total_sold >= 10760.0
