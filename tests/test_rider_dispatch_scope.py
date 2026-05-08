"""Rider txns are scoped to the active dispatch.

After a rider remits, a fresh dispatch on the same day must show a "zero" txn
list — prior dispatch's txns belong to that prior dispatch, not the new one.
This covers write-side stamping + read-side filtering + the no-active-dispatch
block.
"""
import pytest
from app.models.transaction import Transaction, RiderDispatch, DispatchStatus
from app.core.today import get_today
from tests.conftest import auth_header


@pytest.fixture
def usd_setup(db):
    from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition
    today = get_today()
    db.add(Currency(code="USD", name="US Dollar", flag="🇺🇸", category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y"))
    db.add(DailyRate(date=today, currency_code="USD", buy_rate=57.0, sell_rate=58.0, set_by="admintest"))
    db.add(DailyPosition(date=today, currency_code="USD", carry_in_qty=10_000.0, carry_in_rate=57.5))
    db.commit()


class TestDispatchScope:
    def test_rider_txn_stamps_active_dispatch_id(self, client, rider_user, make_dispatch, usd_setup, db):
        d = make_dispatch()
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER",
                "currency": "USD", "foreign_amt": 100, "rate": 57.0,
                "payment_mode": "CASH", "cashier": "ridertest",
            },
        )
        assert r.status_code == 201, r.text
        txn = db.query(Transaction).filter_by(id=r.json()["id"]).first()
        assert txn.dispatch_id == d.id

    def test_rider_txn_blocked_without_active_dispatch(self, client, rider_user, usd_setup):
        # No make_dispatch → no IN_FIELD row exists for ridertest.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER",
                "currency": "USD", "foreign_amt": 100, "rate": 57.0,
                "payment_mode": "CASH", "cashier": "ridertest",
            },
        )
        assert r.status_code == 400
        assert "No active dispatch" in r.json()["detail"]

    def test_rider_today_filters_by_active_dispatch(self, client, rider_user, make_dispatch, usd_setup, db):
        # Dispatch A — record one txn, then remit (close dispatch A).
        a = make_dispatch()
        client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={"type": "BUY", "source": "RIDER", "currency": "USD",
                  "foreign_amt": 100, "rate": 57.0, "payment_mode": "CASH", "cashier": "ridertest"},
        )
        a.status = DispatchStatus.REMITTED
        db.commit()

        # Dispatch B — fresh IN_FIELD.
        b = make_dispatch()
        client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={"type": "BUY", "source": "RIDER", "currency": "USD",
                  "foreign_amt": 50, "rate": 57.5, "payment_mode": "CASH", "cashier": "ridertest"},
        )

        # Rider's /today should show ONLY Dispatch B's single txn.
        r = client.get("/api/v1/transactions/today", headers=auth_header("ridertest", "rider"))
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1, f"expected 1 (Dispatch B only), got {len(body)}: {body}"
        assert body[0]["foreign_amt"] == 50

    def test_rider_batch_stamps_dispatch_id(self, client, rider_user, make_dispatch, usd_setup, db):
        d = make_dispatch()
        r = client.post(
            "/api/v1/transactions/batch",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER", "customer": "Ana",
                "payment_mode": "CASH",
                "items": [{"currency": "USD", "foreign_amt": 100, "rate": 57.0}],
            },
        )
        assert r.status_code == 201, r.text
        txn = db.query(Transaction).filter_by(id=r.json()[0]["id"]).first()
        assert txn.dispatch_id == d.id

    def test_admin_today_unscoped_by_dispatch(self, client, admin_user, rider_user, make_dispatch, usd_setup, db):
        # Rider records under Dispatch A, then remits.
        a = make_dispatch()
        client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={"type": "BUY", "source": "RIDER", "currency": "USD",
                  "foreign_amt": 100, "rate": 57.0, "payment_mode": "CASH", "cashier": "ridertest"},
        )
        a.status = DispatchStatus.REMITTED
        db.commit()

        # Admin still sees the prior dispatch's txn — needed for treasurer
        # confirmation queues that span dispatches.
        r = client.get("/api/v1/transactions/today", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()]
        assert any(i.startswith("RD-") for i in ids)
