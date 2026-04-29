"""
Integration tests for rider dispatch top-ups.

Locks in the cumulative cash_php + audit-row contract that came out of the
2026-04-29 fix: when a treasurer adds mid-shift cash, dispatch.cash_php must
grow (not be overwritten), and every top-up gets an audit row in
rider_dispatch_topups.

Bug this guards against: rider screen showing only the original dispatch
amount because cash_php was being overwritten instead of added.
"""
from sqlalchemy.orm import Session

from app.models.transaction import (
    RiderDispatch, RiderDispatchTopup, DispatchStatus,
)
from tests.conftest import auth_header


# ── Cumulative cash_php + audit row ────────────────────────────────────────────

class TestTopupAccumulates:
    def test_single_topup_adds_to_cash_php(self, client, db: Session, admin_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)

        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 400_000},
            headers=auth_header("admintest", "admin"),
        )

        assert r.status_code == 200, r.text
        assert r.json()["cash_php"] == 700_000

        db.expire_all()
        refreshed = db.query(RiderDispatch).filter_by(id=d.id).first()
        assert refreshed.cash_php == 700_000

    def test_topup_creates_audit_row(self, client, db: Session, admin_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)

        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 400_000, "notes": "second wind"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200

        topups = db.query(RiderDispatchTopup).filter_by(dispatch_id=d.id).all()
        assert len(topups) == 1
        assert topups[0].amount_php == 400_000
        assert topups[0].dispatched_by == "admintest"
        assert topups[0].notes == "second wind"
        assert topups[0].time is not None

    def test_multiple_topups_stack(self, client, db: Session, admin_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)

        for amt in (400_000, 100_000, 50_000):
            r = client.post(
                f"/api/v1/rider/dispatches/{d.id}/topup",
                json={"amount_php": amt},
                headers=auth_header("admintest", "admin"),
            )
            assert r.status_code == 200

        db.expire_all()
        refreshed = db.query(RiderDispatch).filter_by(id=d.id).first()
        assert refreshed.cash_php == 850_000

        topup_rows = db.query(RiderDispatchTopup).filter_by(dispatch_id=d.id).all()
        assert sorted(t.amount_php for t in topup_rows) == [50_000, 100_000, 400_000]


# ── Guards ────────────────────────────────────────────────────────────────────

class TestTopupGuards:
    def test_zero_amount_rejected(self, client, admin_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 0},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 400
        assert "positive" in r.json()["detail"].lower()

    def test_negative_amount_rejected(self, client, admin_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": -1000},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 400

    def test_missing_dispatch_returns_404(self, client, admin_user):
        r = client.post(
            "/api/v1/rider/dispatches/00000000-0000-0000-0000-000000000000/topup",
            json={"amount_php": 1000},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 404

    def test_remitted_dispatch_rejects_topup(self, client, db: Session, admin_user, make_dispatch):
        d = make_dispatch()
        d.status = DispatchStatus.REMITTED
        db.commit()

        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 1000},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 400
        assert "in_field" in r.json()["detail"].lower() or "remit" in r.json()["detail"].lower() or "topup" in r.json()["detail"].lower() or "top up" in r.json()["detail"].lower()


# ── Authorization ─────────────────────────────────────────────────────────────

class TestTopupAuthz:
    def test_supervisor_can_topup(self, client, supervisor_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 1000},
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 200

    def test_rider_cannot_topup_their_own_dispatch(self, client, rider_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 1000},
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 403

    def test_unauthenticated_rejected(self, client, make_dispatch):
        d = make_dispatch()
        r = client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 1000},
        )
        assert r.status_code == 401


# ── PHP coercion on dispatch creation ─────────────────────────────────────────

class TestPhpCoercion:
    def test_php_in_items_folds_into_cash_php(self, client, db: Session, admin_user, rider_user):
        r = client.post(
            "/api/v1/rider/dispatches",
            json={
                "rider_username": "ridertest",
                "cash_php": 100_000,
                "items": [
                    {"currency": "PHP", "amount": 200_000},
                    {"currency": "USD", "amount": 500},
                ],
            },
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["cash_php"] == 300_000
        currencies = [i["currency"] for i in body["items"]]
        assert "PHP" not in currencies
        assert "USD" in currencies


# ── Topups round-trip in GET responses ────────────────────────────────────────

class TestTopupVisibility:
    def test_topups_appear_in_dispatches_today(self, client, admin_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)
        client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 400_000, "notes": "second wind"},
            headers=auth_header("admintest", "admin"),
        )

        r = client.get(
            "/api/v1/rider/dispatches/today",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["cash_php"] == 700_000
        assert len(rows[0]["topups"]) == 1
        assert rows[0]["topups"][0]["amount_php"] == 400_000
        assert rows[0]["topups"][0]["notes"] == "second wind"

    def test_topups_appear_in_rider_my_dispatch(self, client, admin_user, rider_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)
        client.post(
            f"/api/v1/rider/dispatches/{d.id}/topup",
            json={"amount_php": 400_000},
            headers=auth_header("admintest", "admin"),
        )

        r = client.get(
            "/api/v1/rider/my-dispatch",
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dispatch"] is not None
        assert body["dispatch"]["cash_php"] == 700_000
        assert len(body["dispatch"]["topups"]) == 1
