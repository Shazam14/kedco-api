"""
Integration tests for the PENDING payment-status filter on PHP-amount sums.

Rule: PENDING transactions are stored and listed everywhere, but must NOT
be summed into totals that represent money actually in hand or earned today.

Affected routes (all aggregate php_amt):
  GET  /dashboard/summary  → total_bought, total_sold (today)
  GET  /report/daily        → total_bought, total_sold (any day)
  POST /shifts/close        → expected_cash math (driven by total_sold/bought)
  POST /eod/close           → DailySummary totals

Bug this guards against: a PENDING SELL of ₱X inflates today's totals by ₱X
even though no PHP physically changed hands.
"""
from sqlalchemy.orm import Session
from datetime import timedelta

from tests.conftest import auth_header


# ── /dashboard/summary ────────────────────────────────────────────────────────

class TestDashboardSummaryFiltersPending:
    def test_total_sold_excludes_pending(self, client, admin_user, make_transaction):
        make_transaction(type="SELL", php_amt=10_000, payment_status="RECEIVED")
        make_transaction(type="SELL", php_amt=5_000, payment_status="PENDING")

        r = client.get(
            "/api/v1/dashboard/summary",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_sold_today"] == 10_000

    def test_total_bought_excludes_pending(self, client, admin_user, make_transaction):
        make_transaction(type="BUY", php_amt=20_000, payment_status="RECEIVED")
        make_transaction(type="BUY", php_amt=8_000, payment_status="PENDING")

        r = client.get(
            "/api/v1/dashboard/summary",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total_bought_today"] == 20_000

    def test_pending_txns_still_appear_in_recent(self, client, admin_user, make_transaction):
        """Filter is on SUMS, not on visibility."""
        make_transaction(type="SELL", php_amt=10_000, payment_status="RECEIVED")
        make_transaction(type="SELL", php_amt=5_000, payment_status="PENDING")

        r = client.get(
            "/api/v1/dashboard/summary",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        recent = r.json()["recent_transactions"]
        statuses = sorted(t["payment_status"] for t in recent)
        assert statuses == ["PENDING", "RECEIVED"]


# ── /report/daily ─────────────────────────────────────────────────────────────

class TestReportDailyAccrualWithPendingBadge:
    """Daily report is ACCRUAL: PENDING SELL contributes to total_sold_php and
    is also surfaced via total_sold_php_pending so the frontend can render a
    receivables badge. BUYs stay RECEIVED-only (PENDING BUY = we owe customer).
    Spec: see test_report_accrual_with_pending_badge.py."""
    def test_sold_is_accrual_with_pending_split(self, client, admin_user, make_transaction):
        from app.core.today import get_today
        today = get_today()
        make_transaction(type="SELL", php_amt=10_000, payment_status="RECEIVED")
        make_transaction(type="SELL", php_amt=5_000, payment_status="PENDING")
        make_transaction(type="BUY", php_amt=20_000, payment_status="RECEIVED")
        make_transaction(type="BUY", php_amt=8_000, payment_status="PENDING")

        r = client.get(
            f"/api/v1/report/daily?date={today.isoformat()}",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_sold_php"] == 15_000           # accrual
        assert body["total_sold_php_pending"] == 5_000    # receivables badge
        assert body["pending_count"] == 2                 # 1 SELL + 1 BUY pending
        assert body["total_bought_php"] == 20_000         # RECEIVED only


# ── /shifts/close — expected_cash math ────────────────────────────────────────

class TestShiftCloseFiltersPending:
    def test_expected_cash_excludes_pending(self, client, cashier_user, make_transaction):
        """A PENDING SELL didn't bring PHP into the till — must not inflate expected_cash."""
        opened = client.post(
            "/api/v1/shifts/open",
            json={"opening_cash_php": 10_000},
            headers=auth_header("cashiertest", "cashier"),
        )
        assert opened.status_code == 201, opened.text

        make_transaction(type="SELL", php_amt=5_000, payment_status="RECEIVED", cashier="cashiertest")
        make_transaction(type="SELL", php_amt=2_000, payment_status="PENDING",  cashier="cashiertest")

        # If cashier hands back exactly opening + received SELL, variance should be zero.
        closed = client.post(
            "/api/v1/shifts/close",
            json={"closing_cash_php": 15_000},
            headers=auth_header("cashiertest", "cashier"),
        )
        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["expected_cash_php"] == 15_000
        assert body["cash_variance"] == 0
        assert body["total_sold_php"] == 5_000
