"""
BSP Quarterly MC/FX Volume Report — role gate + computation correctness.

Why: This is the regulatory output BSP wants under Circular 1222. Wrong totals
or accidental delegation past admin would be costly. EXCESS must not appear in
the peso volume (no money moves), and the quarter window math must align with
calendar quarters (BSP reports by calendar quarter, not fiscal year).
"""
from datetime import date

from app.models.transaction import Transaction, TxnType, TxnSource, PaymentMode, PaymentStatus
from tests.conftest import auth_header


def _txn(db, *, txn_id: str, d: date, type_: str, code: str, php: float, branch: str = "MAIN"):
    db.add(Transaction(
        id=txn_id,
        date=d,
        time="09:00",
        type=type_,
        source=TxnSource.COUNTER,
        currency_code=code,
        foreign_amt=100.0,
        rate=php / 100.0 if php else 0.0,
        php_amt=php,
        daily_avg_cost=0.0,
        than=0.0,
        cashier="cashiertest",
        payment_mode=PaymentMode.CASH,
        payment_status=PaymentStatus.RECEIVED,
        branch_id=branch,
    ))


class TestBspRoleGate:
    def test_admin_can_read_quarterly_volume(self, client, admin_user, db):
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text

    def test_admin_can_read_monthly_volume(self, client, admin_user, db):
        r = client.get(
            "/api/v1/bsp/monthly-volume?months=6",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text

    def test_supervisor_cannot_read_quarterly_volume(self, client, supervisor_user, db):
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 403

    def test_cashier_cannot_read_quarterly_volume(self, client, cashier_user, db):
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 403

    def test_cashier_cannot_read_monthly_volume(self, client, cashier_user, db):
        r = client.get(
            "/api/v1/bsp/monthly-volume",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 403


class TestQuarterlyVolumeMath:
    def _seed_q1(self, db):
        # Q1 2026 = Jan 1 – Mar 31. Three buys + two sells + one excess.
        _txn(db, txn_id="OR-Q1-001", d=date(2026, 1, 15), type_=TxnType.BUY,    code="USD", php=100_000.0)
        _txn(db, txn_id="OR-Q1-002", d=date(2026, 2, 20), type_=TxnType.BUY,    code="USD", php=200_000.0, branch="CTS")
        _txn(db, txn_id="OR-Q1-003", d=date(2026, 3, 10), type_=TxnType.BUY,    code="EUR", php=300_000.0)
        _txn(db, txn_id="OR-Q1-004", d=date(2026, 1, 25), type_=TxnType.SELL,   code="USD", php=150_000.0)
        _txn(db, txn_id="OR-Q1-005", d=date(2026, 3, 28), type_=TxnType.SELL,   code="EUR", php=250_000.0, branch="CTS")
        _txn(db, txn_id="OR-Q1-EXC", d=date(2026, 2, 14), type_=TxnType.EXCESS, code="USD", php=0.0)
        # Out of quarter — should be excluded.
        _txn(db, txn_id="OR-Q4-001", d=date(2025, 12, 31), type_=TxnType.BUY,   code="USD", php=999_999.0)
        _txn(db, txn_id="OR-Q2-001", d=date(2026, 4, 1),   type_=TxnType.BUY,   code="USD", php=999_999.0)
        db.commit()

    def test_q1_totals_exclude_excess_and_other_quarters(self, client, admin_user, db):
        self._seed_q1(db)
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        data = r.json()

        assert data["period"]["from"] == "2026-01-01"
        assert data["period"]["to"]   == "2026-03-31"
        assert data["totals"]["buy_count"]   == 3
        assert data["totals"]["sell_count"]  == 2
        assert data["totals"]["buy_php"]     == 600_000.0   # 100k+200k+300k
        assert data["totals"]["sell_php"]    == 400_000.0   # 150k+250k
        assert data["totals"]["total_php"]   == 1_000_000.0

    def test_q1_by_currency_split(self, client, admin_user, db):
        self._seed_q1(db)
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("admintest", "admin"),
        )
        ccy = {row["currency"]: row for row in r.json()["by_currency"]}
        assert ccy["USD"]["buy_php"]  == 300_000.0
        assert ccy["USD"]["sell_php"] == 150_000.0
        assert ccy["EUR"]["buy_php"]  == 300_000.0
        assert ccy["EUR"]["sell_php"] == 250_000.0

    def test_q1_by_branch_split(self, client, admin_user, db):
        self._seed_q1(db)
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("admintest", "admin"),
        )
        br = {row["branch_id"]: row for row in r.json()["by_branch"]}
        # MAIN: BUY 100k (USD) + 300k (EUR) + SELL 150k (USD) = 550k
        assert br["MAIN"]["total_php"] == 550_000.0
        # CTS:  BUY 200k (USD)         + SELL 250k (EUR)        = 450k
        assert br["CTS"]["total_php"]  == 450_000.0

    def test_q1_by_month_breakdown(self, client, admin_user, db):
        self._seed_q1(db)
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=1",
            headers=auth_header("admintest", "admin"),
        )
        months = {row["month"]: row for row in r.json()["by_month"]}
        assert months["2026-01"]["total_php"] == 250_000.0
        assert months["2026-02"]["total_php"] == 200_000.0
        assert months["2026-03"]["total_php"] == 550_000.0

    def test_invalid_quarter_rejected(self, client, admin_user, db):
        r = client.get(
            "/api/v1/bsp/quarterly-volume?year=2026&quarter=5",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 422


class TestMonthlyVolume:
    def test_threshold_flag_and_average(self, client, admin_user, db):
        # ₱60M in Jan 2026 (above ₱50M) + ₱10M in Feb 2026 (below)
        _txn(db, txn_id="OR-MO-001", d=date(2026, 1, 10), type_=TxnType.BUY,  code="USD", php=60_000_000.0)
        _txn(db, txn_id="OR-MO-002", d=date(2026, 2, 10), type_=TxnType.SELL, code="USD", php=10_000_000.0)
        db.commit()

        r = client.get(
            "/api/v1/bsp/monthly-volume?months=12",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["threshold_php"] == 50_000_000.0
        # At least one month should be flagged above
        flagged = [s for s in data["series"] if s["above_type_f"]]
        assert any(s["month"] == "2026-01" for s in flagged)
        assert data["months_above"] >= 1
        assert data["currently_type_f"] is False
