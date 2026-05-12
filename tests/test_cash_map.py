"""
Tests for GET /api/v1/cash-map — the live cash-location rollup.
"""
import pytest
from datetime import datetime, timezone

from app.models.shift import (
    TellerShift, ShiftStatus, CashReplenishment, SafeMovement,
)
from app.models.transaction import (
    RiderDispatch, DispatchStatus,
)
from app.core.today import get_today
from tests.conftest import auth_header


@pytest.fixture(autouse=True)
def _clear_cash_map_cache():
    from app.api.v1 import cash_map as _cm
    _cm._cache.clear()
    yield
    _cm._cache.clear()


class TestCashMapAuthorization:

    def test_cashier_role_forbidden(self, client, cashier_user):
        r = client.get("/api/v1/cash-map", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 403

    def test_supervisor_allowed(self, client, supervisor_user):
        r = client.get("/api/v1/cash-map", headers=auth_header("supervisortest", "supervisor"))
        assert r.status_code == 200

    def test_admin_allowed(self, client, admin_user):
        r = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200


class TestCashMapEmpty:

    def test_empty_state_returns_zero_rollup(self, client, admin_user):
        r = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin"))
        body = r.json()
        assert body["rollup"]["cashiers"]["drawer"] == 0
        assert body["rollup"]["cashiers"]["handoff"] == 0
        assert body["rollup"]["riders"]["in_field"] == 0
        assert body["rollup"]["riders"]["remitted_unconfirmed"] == 0
        assert body["rollup"]["vault"] == 0
        assert body["rollup"]["total"] == 0

    def test_vault_row_always_present(self, client, admin_user):
        # Even with zero movements, vault still surfaces as a row so the UI
        # can render the bucket with amount = 0.
        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        vault_rows = [r for r in body["rows"] if r["location"] == "Vault"]
        assert len(vault_rows) == 1
        assert vault_rows[0]["amount"] == 0


class TestCashierDrawer:

    def test_open_cashier_shift_contributes_to_drawer(self, client, admin_user, cashier_user, db):
        today = get_today()
        db.add(TellerShift(
            date=today, cashier="cashiertest", cashier_name="Cashier Test",
            status=ShiftStatus.OPEN, opening_cash_php=150_000,
            opened_at=datetime.now(timezone.utc),
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["cashiers"]["drawer"] == 150_000
        cashier_rows = [r for r in body["rows"] if r["location"] == "Cashier Drawer"]
        assert len(cashier_rows) == 1
        assert cashier_rows[0]["holder"] == "Cashier Test"
        assert cashier_rows[0]["status"] == "OPEN"

    def test_replenishment_increases_drawer(self, client, admin_user, cashier_user, db):
        today = get_today()
        shift = TellerShift(
            date=today, cashier="cashiertest", cashier_name="Cashier Test",
            status=ShiftStatus.OPEN, opening_cash_php=100_000,
            opened_at=datetime.now(timezone.utc),
        )
        db.add(shift); db.commit(); db.refresh(shift)
        db.add(CashReplenishment(shift_id=shift.id, amount_php=25_000))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["cashiers"]["drawer"] == 125_000


class TestCashierHandoff:

    def test_closed_cashier_no_treasurer_goes_to_handoff(
        self, client, admin_user, cashier_user, db,
    ):
        today = get_today()
        db.add(TellerShift(
            date=today, cashier="cashiertest", cashier_name="Cashier Test",
            status=ShiftStatus.CLOSED, opening_cash_php=100_000,
            closing_cash_php=180_000,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["cashiers"]["handoff"] == 180_000
        handoff_rows = [r for r in body["rows"] if r["location"] == "Cashier Handoff"]
        assert len(handoff_rows) == 1
        assert handoff_rows[0]["status"] == "CLOSED"

    def test_closed_cashier_absorbed_when_treasurer_open(
        self, client, admin_user, cashier_user, supervisor_user, db,
    ):
        today = get_today()
        # Closed cashier
        db.add(TellerShift(
            date=today, cashier="cashiertest", cashier_name="Cashier Test",
            status=ShiftStatus.CLOSED, opening_cash_php=100_000,
            closing_cash_php=180_000,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        ))
        # Open treasurer
        db.add(TellerShift(
            date=today, cashier="supervisortest", cashier_name="Supervisor Test",
            status=ShiftStatus.OPEN, opening_cash_php=500_000,
            opened_at=datetime.now(timezone.utc),
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        # Handoff bucket is zero — treasurer's drawer math already counts the
        # closed cashier's closing via from_cashier in _treasurer_aggregates.
        assert body["rollup"]["cashiers"]["handoff"] == 0


class TestRiderBuckets:

    def test_in_field_dispatch_contributes_starting_cash(
        self, client, admin_user, make_dispatch,
    ):
        make_dispatch(cash_php=400_000)
        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["riders"]["in_field"] == 400_000

    def test_remitted_dispatch_uses_remit_php(self, client, admin_user, make_dispatch, db):
        d = make_dispatch(cash_php=400_000)
        d.status = DispatchStatus.REMITTED
        d.remit_php = 250_000
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        # IN_FIELD bucket empty (status flipped); REMITTED bucket has remit_php.
        assert body["rollup"]["riders"]["in_field"] == 0
        assert body["rollup"]["riders"]["remitted_unconfirmed"] == 250_000

    def test_returned_dispatch_drops_from_buckets(self, client, admin_user, make_dispatch, db):
        d = make_dispatch(cash_php=400_000)
        d.status = DispatchStatus.RETURNED
        d.remit_php = 250_000
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        # RETURNED = treasurer confirmed; cash is in her drawer now.
        assert body["rollup"]["riders"]["in_field"] == 0
        assert body["rollup"]["riders"]["remitted_unconfirmed"] == 0


class TestVaultBucket:

    def test_safe_movements_sum_into_vault(self, client, admin_user, db):
        today = get_today()
        db.add(SafeMovement(
            amount_php=500_000, reason="MANUAL_DEPOSIT",
            actor_username="admintest", movement_date=today,
        ))
        db.add(SafeMovement(
            amount_php=-120_000, reason="MANUAL_WITHDRAWAL",
            actor_username="admintest", movement_date=today,
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["vault"] == 380_000

    def test_vault_includes_historical_movements(self, client, admin_user, db):
        from datetime import date
        db.add(SafeMovement(
            amount_php=1_000_000, reason="MANUAL_DEPOSIT",
            actor_username="admintest", movement_date=date(2026, 1, 1),
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["vault"] == 1_000_000


class TestRollupTotal:

    def test_total_sums_all_buckets(self, client, admin_user, cashier_user, make_dispatch, db):
        today = get_today()
        db.add(TellerShift(
            date=today, cashier="cashiertest", cashier_name="Cashier Test",
            status=ShiftStatus.OPEN, opening_cash_php=100_000,
            opened_at=datetime.now(timezone.utc),
        ))
        db.add(SafeMovement(
            amount_php=200_000, reason="MANUAL_DEPOSIT",
            actor_username="admintest", movement_date=today,
        ))
        db.commit()
        make_dispatch(cash_php=300_000)

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        # 100k cashier drawer + 300k rider field + 200k vault = 600k
        assert body["rollup"]["total"] == 600_000


class TestDemoUserExclusion:

    def test_demo_user_shift_excluded(self, client, admin_user, db):
        from app.models.user import User
        from app.core.security import hash_password
        today = get_today()
        demo = User(
            username="demotest", full_name="Demo Test",
            password_hash=hash_password("x"), role="cashier", is_demo=True,
        )
        db.add(demo)
        db.add(TellerShift(
            date=today, cashier="demotest", cashier_name="Demo Test",
            status=ShiftStatus.OPEN, opening_cash_php=999_999,
            opened_at=datetime.now(timezone.utc),
        ))
        db.commit()

        body = client.get("/api/v1/cash-map", headers=auth_header("admintest", "admin")).json()
        assert body["rollup"]["cashiers"]["drawer"] == 0
