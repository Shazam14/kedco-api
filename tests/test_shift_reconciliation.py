"""
GAP_CHECK Phase 2 — PATCH /api/v1/shifts/{id}/reconciliation
plus exposure of reconciliation_* fields on /report/daily peso block.

Lets admin/treasurer annotate the variance between expected and declared
closing peso, and track whether it's been reviewed.
"""
from datetime import datetime, timezone, timedelta

from app.core.today import get_today
from app.models.shift import TellerShift, ShiftStatus
from tests.conftest import auth_header, _make_user

TODAY = get_today()
TODAY_ISO = TODAY.isoformat()


def _add_closed_treasurer_shift(db, *, username="treas1", variance=1_234.50):
    now = datetime.now(timezone.utc)
    s = TellerShift(
        date=TODAY,
        cashier=username,
        cashier_name=username,
        status=ShiftStatus.CLOSED,
        opened_at=now - timedelta(hours=8),
        closed_at=now,
        opening_cash_php=2_000_000.0,
        closing_cash_php=2_500_000.0 + variance,
        expected_cash_php=2_500_000.0,
        cash_variance=variance,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


class TestReconciliationPatch:
    def test_pending_by_default_in_report(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        _add_closed_treasurer_shift(db)
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["reconciliation_status"] == "PENDING"
        assert peso["reconciliation_note"] is None
        assert peso["reconciliation_shift_id"] is not None

    def test_save_note_flips_status_to_noted(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"note": "₱1,234.50 is paniloy from Lulu — to confirm"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reconciliation_status"] == "NOTED"
        assert body["reconciliation_note"].startswith("₱1,234.50")

        # And the daily report surfaces it.
        rep = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = rep.json()["peso"]
        assert peso["reconciliation_status"] == "NOTED"
        assert "Lulu" in peso["reconciliation_note"]

    def test_explicit_resolved_status_stored(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"note": "Lulu confirmed", "status": "RESOLVED"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["reconciliation_status"] == "RESOLVED"

    def test_blank_note_keeps_pending(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"note": "   "},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        assert r.json()["reconciliation_status"] == "PENDING"
        assert r.json()["reconciliation_note"] is None

    def test_supervisor_can_save(self, client, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"note": "rounding"},
            headers=auth_header("treas1", "supervisor"),
        )
        assert r.status_code == 200

    def test_cashier_cannot_save(self, client, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        _make_user(db, "casher1", "cashier", "Cashier 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"note": "should fail"},
            headers=auth_header("casher1", "cashier"),
        )
        assert r.status_code == 403

    def test_invalid_status_rejected(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        shift = _add_closed_treasurer_shift(db)
        r = client.patch(
            f"/api/v1/shifts/{shift.id}/reconciliation",
            json={"status": "BOGUS"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 400

    def test_unknown_shift_404(self, client, admin_user, db):
        r = client.patch(
            "/api/v1/shifts/00000000-0000-0000-0000-000000000000/reconciliation",
            json={"note": "x"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 404
