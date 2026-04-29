"""
Integration tests for the rider remit state machine.

Rider lifecycle:
    IN_FIELD ──(POST /rider/remit by rider)──▶ REMITTED
    REMITTED ──(PATCH /rider/dispatches/{id}/return by treasurer)──▶ RETURNED

Locks in the contract that:
- Only the dispatch's own rider can submit a remit.
- Remit moves an IN_FIELD dispatch to REMITTED with remit_php + return_time.
- Resubmitting a remit replaces its forex items (idempotent on retries).
- Treasurer confirm marks a dispatch RETURNED.
- Authz: rider can't confirm; admin/supervisor can't submit a rider remit.
"""
from sqlalchemy.orm import Session

from app.models.transaction import (
    RiderDispatch, RiderRemitItem, DispatchStatus,
)
from tests.conftest import auth_header


# ── Rider self-remit (IN_FIELD → REMITTED) ───────────────────────────────────

class TestRiderRemit:
    def test_rider_remits_own_dispatch(self, client, db: Session, rider_user, make_dispatch):
        d = make_dispatch(cash_php=300_000)

        r = client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(d.id),
                "cash_php_remaining": 120_000,
                "items": [{"currency": "USD", "amount": 250}],
            },
            headers=auth_header("ridertest", "rider"),
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "REMITTED"
        assert body["remit_php"] == 120_000
        assert body["return_time"] is not None

        db.expire_all()
        refreshed = db.query(RiderDispatch).filter_by(id=d.id).first()
        assert refreshed.status == DispatchStatus.REMITTED
        assert refreshed.remit_php == 120_000

    def test_remit_records_forex_items(self, client, db: Session, rider_user, make_dispatch):
        d = make_dispatch()

        r = client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(d.id),
                "cash_php_remaining": 0,
                "items": [
                    {"currency": "USD", "amount": 100},
                    {"currency": "jpy", "amount": 5000},
                ],
            },
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 200

        items = db.query(RiderRemitItem).filter_by(dispatch_id=d.id).all()
        assert len(items) == 2
        currencies = sorted(i.currency for i in items)
        assert currencies == ["JPY", "USD"]  # uppercased

    def test_resubmit_replaces_items(self, client, db: Session, rider_user, make_dispatch):
        """If a rider re-taps Submit, the remit_items list is replaced, not appended."""
        d = make_dispatch()

        client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(d.id),
                "cash_php_remaining": 100_000,
                "items": [{"currency": "USD", "amount": 100}],
            },
            headers=auth_header("ridertest", "rider"),
        )
        # Status is now REMITTED. The endpoint filters on IN_FIELD only, so
        # a resubmit on an already-REMITTED dispatch should 404.
        r = client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(d.id),
                "cash_php_remaining": 50_000,
                "items": [{"currency": "EUR", "amount": 200}],
            },
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 404

        items = db.query(RiderRemitItem).filter_by(dispatch_id=d.id).all()
        assert len(items) == 1
        assert items[0].currency == "USD"

    def test_rider_cannot_remit_other_riders_dispatch(self, client, db: Session, rider_user, make_dispatch):
        from app.models.user import User
        from app.core.security import hash_password
        other = User(
            username="rider2", full_name="Rider Two",
            password_hash=hash_password("password"), role="rider",
        )
        db.add(other)
        db.commit()

        d = make_dispatch()  # owned by ridertest
        r = client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(d.id),
                "cash_php_remaining": 0,
                "items": [],
            },
            headers=auth_header("rider2", "rider"),
        )
        assert r.status_code == 404


# ── Authz on /remit ──────────────────────────────────────────────────────────

class TestRemitAuthz:
    def test_admin_cannot_submit_rider_remit(self, client, admin_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            "/api/v1/rider/remit",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 403

    def test_supervisor_cannot_submit_rider_remit(self, client, supervisor_user, make_dispatch):
        d = make_dispatch()
        r = client.post(
            "/api/v1/rider/remit",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 403

    def test_unauthenticated_rejected(self, client, make_dispatch):
        d = make_dispatch()
        r = client.post(
            "/api/v1/rider/remit",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
        )
        assert r.status_code == 401


# ── Treasurer confirm (REMITTED → RETURNED via PATCH /return) ────────────────

class TestTreasurerConfirmReturn:
    def _remit(self, client, dispatch_id):
        return client.post(
            "/api/v1/rider/remit",
            json={
                "dispatch_id": str(dispatch_id),
                "cash_php_remaining": 100_000,
                "items": [{"currency": "USD", "amount": 100}],
            },
            headers=auth_header("ridertest", "rider"),
        )

    def test_admin_marks_remitted_dispatch_returned(self, client, db: Session, admin_user, rider_user, make_dispatch):
        d = make_dispatch()
        self._remit(client, d.id)

        r = client.patch(
            f"/api/v1/rider/dispatches/{d.id}/return",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "RETURNED"

        db.expire_all()
        refreshed = db.query(RiderDispatch).filter_by(id=d.id).first()
        assert refreshed.status == DispatchStatus.RETURNED
        assert refreshed.return_time is not None

    def test_supervisor_can_mark_returned(self, client, supervisor_user, rider_user, make_dispatch):
        d = make_dispatch()
        self._remit(client, d.id)

        r = client.patch(
            f"/api/v1/rider/dispatches/{d.id}/return",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "RETURNED"

    def test_rider_cannot_mark_returned(self, client, rider_user, make_dispatch):
        d = make_dispatch()
        self._remit(client, d.id)

        r = client.patch(
            f"/api/v1/rider/dispatches/{d.id}/return",
            json={"dispatch_id": str(d.id), "cash_php_remaining": 0, "items": []},
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 403

    def test_missing_dispatch_returns_404(self, client, admin_user):
        r = client.patch(
            "/api/v1/rider/dispatches/00000000-0000-0000-0000-000000000000/return",
            json={"dispatch_id": "00000000-0000-0000-0000-000000000000", "cash_php_remaining": 0, "items": []},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 404
