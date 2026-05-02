"""
Tests for the safe / vault ledger.

Two surfaces:
  - GET/POST /api/v1/safe and /safe/movements (manual ledger entries)
  - POST /api/v1/shifts/replenish with source=SAFE writes a paired
    safe_movement(-amount), so the cash flow is honest end-to-end.
"""
import pytest
from datetime import datetime, timezone

from app.models.shift import TellerShift, ShiftStatus, CashReplenishment, SafeMovement
from app.core.today import get_today
from tests.conftest import auth_header


@pytest.fixture
def open_shift(db, cashier_user):
    today = get_today()
    s = TellerShift(
        date=today,
        cashier="cashiertest",
        cashier_name="Cashier Test",
        status=ShiftStatus.OPEN,
        opening_cash_php=100_000,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


class TestSafeEndpoint:

    def test_empty_safe_returns_zero_net(self, client, admin_user):
        r = client.get("/api/v1/safe", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        body = r.json()
        assert body["today_net"]   == 0
        assert body["running_net"] == 0
        assert body["movements"]   == []

    def test_post_movement_then_read_back(self, client, admin_user):
        r = client.post(
            "/api/v1/safe/movements",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": 50_000, "reason": "MANUAL_DEPOSIT", "note": "evening drop"},
        )
        assert r.status_code == 201
        movement = r.json()
        assert movement["amount_php"] == 50_000
        assert movement["reason"]     == "MANUAL_DEPOSIT"
        assert movement["actor_username"] == "admintest"

        r2 = client.get("/api/v1/safe", headers=auth_header("admintest", "admin"))
        assert r2.json()["today_net"]   == 50_000
        assert r2.json()["running_net"] == 50_000
        assert len(r2.json()["movements"]) == 1

    def test_running_net_includes_past_movements(self, client, admin_user, db):
        # A movement from a prior date is in running_net but not today_net.
        from datetime import date
        db.add(SafeMovement(
            amount_php=200_000, reason="MANUAL_DEPOSIT",
            actor_username="admintest", movement_date=date(2026, 1, 1),
        )); db.commit()

        client.post(
            "/api/v1/safe/movements",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": -30_000, "reason": "MANUAL_WITHDRAWAL"},
        )
        body = client.get("/api/v1/safe", headers=auth_header("admintest", "admin")).json()
        assert body["today_net"]   == -30_000
        assert body["running_net"] == 170_000

    def test_zero_amount_rejected(self, client, admin_user):
        r = client.post(
            "/api/v1/safe/movements",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": 0, "reason": "OTHER"},
        )
        assert r.status_code == 400

    def test_invalid_reason_rejected(self, client, admin_user):
        r = client.post(
            "/api/v1/safe/movements",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": 100, "reason": "MADE_UP_REASON"},
        )
        assert r.status_code == 400

    def test_cashier_role_forbidden(self, client, cashier_user):
        r = client.get("/api/v1/safe", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 403


class TestReplenishSourcePairing:

    def test_safe_replenish_writes_paired_movement(self, client, db, open_shift):
        r = client.post(
            "/api/v1/shifts/replenish",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 50_000, "note": "morning top-up", "source": "SAFE"},
        )
        assert r.status_code == 200

        # Replenishment row was tagged SAFE
        repls = db.query(CashReplenishment).all()
        assert len(repls) == 1
        assert repls[0].source == "SAFE"

        # Paired safe_movement was written with negative amount
        movements = db.query(SafeMovement).all()
        assert len(movements) == 1
        assert movements[0].amount_php == -50_000
        assert movements[0].reason == "REPLENISH_DRAWER"
        assert movements[0].related_replenishment_id == repls[0].id

    def test_treasurer_float_replenish_does_not_touch_safe(self, client, db, open_shift):
        r = client.post(
            "/api/v1/shifts/replenish",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 50_000, "source": "TREASURER_FLOAT"},
        )
        assert r.status_code == 200
        assert db.query(SafeMovement).count() == 0

    def test_default_source_is_treasurer_float(self, client, db, open_shift):
        # Legacy callers that omit `source` still work.
        r = client.post(
            "/api/v1/shifts/replenish",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 25_000},
        )
        assert r.status_code == 200
        assert db.query(CashReplenishment).all()[0].source == "TREASURER_FLOAT"
        assert db.query(SafeMovement).count() == 0

    def test_invalid_source_rejected(self, client, open_shift):
        r = client.post(
            "/api/v1/shifts/replenish",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 1, "source": "MADE_UP"},
        )
        assert r.status_code == 400


class TestDailyReportIncludesSafe:

    def test_safe_block_appears_in_daily_report(self, client, db, admin_user):
        client.post(
            "/api/v1/safe/movements",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": -100_000, "reason": "REPLENISH_DRAWER", "note": "afternoon"},
        )
        report = client.get("/api/v1/report/daily", headers=auth_header("admintest", "admin")).json()
        assert "safe" in report
        assert report["safe"]["today_net"] == -100_000
        assert len(report["safe"]["movements"]) == 1
