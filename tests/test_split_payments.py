"""
Phase 2 — POST /transactions/ accepts an optional `payments[]` array.
Backward-compat: omitting it = single slice mirroring legacy single-method shape.

Locked rules covered here:
  • Sum of slices must equal php_amt (else 400).
  • Parent payment_mode = first slice's method (transition-glue read).
  • Parent payment_status = RECEIVED iff every slice RECEIVED, else PENDING.
  • Rider non-CASH sell slices forced PENDING (mirrors single-method rule).
  • confirm-payment flips parent AND every pending slice in one shot.
"""
import pytest
from tests.conftest import auth_header


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


class TestLegacyShapeStillWorks:
    def test_omitted_payments_writes_single_slice(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payment_mode": "CASH",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["payment_mode"] == "CASH"
        assert body["payment_status"] == "RECEIVED"
        assert len(body["payments"]) == 1
        assert body["payments"][0]["method"] == "CASH"
        assert body["payments"][0]["amount_php"] == 5800.0
        assert body["payments"][0]["status"] == "RECEIVED"


class TestSplitPaymentPersists:
    def test_two_slice_split_sums_to_php_amt(self, client, cashier_user, usd_setup):
        # ₱5,800 SELL paid as ₱2,000 cash + ₱3,800 GCash.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0},
                    {"method": "GCASH", "amount_php": 3800.0, "reference_no": "GC-12345"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        slices = body["payments"]
        assert len(slices) == 2
        assert sum(s["amount_php"] for s in slices) == 5800.0
        assert {s["method"] for s in slices} == {"CASH", "GCASH"}
        gcash = next(s for s in slices if s["method"] == "GCASH")
        assert gcash["reference_no"] == "GC-12345"

    def test_parent_method_is_first_slice(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "BANK_TRANSFER", "amount_php": 5800.0},
                ],
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_mode"] == "BANK_TRANSFER"

    def test_sum_mismatch_returns_400(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0},
                    {"method": "GCASH", "amount_php": 1000.0},  # short ₱2,800
                ],
            },
        )
        assert r.status_code == 400
        assert "does not match" in r.json()["detail"]


class TestParentStatusAggregation:
    def test_any_pending_slice_makes_parent_pending(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",   "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "CHEQUE", "amount_php": 3800.0, "status": "PENDING"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "PENDING"

    def test_all_received_makes_parent_received(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0},
                    {"method": "GCASH", "amount_php": 3800.0},
                ],
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "RECEIVED"


class TestRiderSplitForcesNonCashPending:
    """Rider sells: only the cash portion lands in-hand. Non-cash slices
    must be PENDING regardless of what client sent — mirrors the existing
    single-method rule, applied per-slice."""
    def test_rider_cash_plus_gcash_only_cash_received(self, client, rider_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "SELL", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "ridertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "GCASH", "amount_php": 3800.0, "status": "RECEIVED"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        cash  = next(s for s in body["payments"] if s["method"] == "CASH")
        gcash = next(s for s in body["payments"] if s["method"] == "GCASH")
        assert cash["status"]  == "RECEIVED"
        assert gcash["status"] == "PENDING"  # forced regardless of client input
        assert body["payment_status"] == "PENDING"  # aggregate


class TestConfirmPaymentClearsAllSlices:
    def test_confirm_flips_parent_and_pending_slices(self, client, cashier_user, usd_setup):
        # Counter sell with one received + one pending slice.
        create = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",   "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "CHEQUE", "amount_php": 3800.0, "status": "PENDING"},
                ],
            },
        )
        assert create.status_code == 201
        txn_id = create.json()["id"]
        assert create.json()["payment_status"] == "PENDING"

        # Treasurer confirms.
        confirm = client.patch(
            f"/api/v1/rider/transactions/{txn_id}/confirm-payment",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert confirm.status_code == 200, confirm.text

        # Re-read via GET /today and verify both parent + slices flipped.
        today = client.get(
            "/api/v1/transactions/today",
            headers=auth_header("admintest", "admin"),
        )
        assert today.status_code == 200
        row = next(t for t in today.json() if t["id"] == txn_id)
        assert row["payment_status"] == "RECEIVED"
        assert all(s["status"] == "RECEIVED" for s in row["payments"])
        # Treasurer's stamp lands only on slices that *were* pending.
        # The cash slice keeps its original cashier confirmation.
        cash   = next(s for s in row["payments"] if s["method"] == "CASH")
        cheque = next(s for s in row["payments"] if s["method"] == "CHEQUE")
        assert cash["confirmed_by"]   == "cashiertest"
        assert cheque["confirmed_by"] == "supervisortest"


class TestSliceAlsoWrittenForLegacyShape:
    """Even when client uses the old single-method shape, a slice row is now
    persisted. Phase 4 reports will read from txn_payments; this test guards
    that the legacy write-path stays in lockstep."""
    def test_legacy_post_persists_one_slice_row(self, client, db, cashier_user, usd_setup):
        from app.models.transaction import TxnPayment
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "cashiertest",
                "payment_mode": "CASH",
            },
        )
        assert r.status_code == 201
        rows = db.query(TxnPayment).filter_by(txn_id=r.json()["id"]).all()
        assert len(rows) == 1
        assert rows[0].amount_php == 5700.0
        assert rows[0].method.value == "CASH"


class TestEditRequestApprovalScalesSlices:
    """Phase 6 — when admin approves an edit on a split txn that changes the rate
    or foreign_amt, the parent's php_amt is recomputed AND the slice amounts are
    scaled proportionally so sum(slices) stays equal to parent.php_amt. Without
    this, daily reports would silently leak the difference."""

    def test_rate_change_scales_two_slice_sell(self, client, db, admin_user, cashier_user, usd_setup):
        from app.models.transaction import TxnPayment

        # 1) Cashier creates a 100 USD SELL @ 58.0 → 5800 PHP, paid CASH 2000 + GCASH 3800.
        create = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0},
                    {"method": "GCASH", "amount_php": 3800.0, "status": "PENDING"},
                ],
            },
        )
        assert create.status_code == 201, create.text
        txn_id = create.json()["id"]

        # 2) Cashier submits an edit-request: bump rate from 58.0 → 59.0 (new php_amt = 5900).
        edit = client.post(
            f"/api/v1/transactions/{txn_id}/edit-request",
            headers=auth_header("cashiertest", "cashier"),
            json={"rate": 59.0, "note": "wrong sell rate"},
        )
        assert edit.status_code == 200, edit.text
        req_id = edit.json()["id"]

        # 3) Admin approves.
        approve = client.post(
            f"/api/v1/admin/edit-requests/{req_id}/approve",
            headers=auth_header("admintest", "admin"),
        )
        assert approve.status_code == 200, approve.text

        # 4) Slices should now sum to 5900 (scaled from 5800).
        rows = db.query(TxnPayment).filter_by(txn_id=txn_id).all()
        assert len(rows) == 2
        total = round(sum(r.amount_php for r in rows), 2)
        assert total == 5900.0, f"slice sum {total} ≠ parent php_amt 5900.0"
        # Methods/statuses preserved
        assert {r.method.value for r in rows} == {"CASH", "GCASH"}

    def test_rate_change_syncs_single_slice_legacy_txn(self, client, db, admin_user, cashier_user, usd_setup):
        from app.models.transaction import TxnPayment

        # Single-slice (legacy shape) txn.
        create = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payment_mode": "CASH",
            },
        )
        assert create.status_code == 201
        txn_id = create.json()["id"]

        edit = client.post(
            f"/api/v1/transactions/{txn_id}/edit-request",
            headers=auth_header("cashiertest", "cashier"),
            json={"foreign_amt": 200.0},  # 200 * 58 = 11600
        )
        req_id = edit.json()["id"]
        client.post(
            f"/api/v1/admin/edit-requests/{req_id}/approve",
            headers=auth_header("admintest", "admin"),
        )

        rows = db.query(TxnPayment).filter_by(txn_id=txn_id).all()
        assert len(rows) == 1
        assert rows[0].amount_php == 11600.0

    def test_customer_only_change_does_not_touch_slices(self, client, db, admin_user, cashier_user, usd_setup):
        from app.models.transaction import TxnPayment

        create = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",  "amount_php": 2000.0},
                    {"method": "GCASH", "amount_php": 3800.0, "status": "PENDING"},
                ],
            },
        )
        txn_id = create.json()["id"]
        before = sorted([(r.method.value, r.amount_php) for r in db.query(TxnPayment).filter_by(txn_id=txn_id).all()])

        edit = client.post(
            f"/api/v1/transactions/{txn_id}/edit-request",
            headers=auth_header("cashiertest", "cashier"),
            json={"customer": "Maria"},
        )
        req_id = edit.json()["id"]
        client.post(
            f"/api/v1/admin/edit-requests/{req_id}/approve",
            headers=auth_header("admintest", "admin"),
        )

        after = sorted([(r.method.value, r.amount_php) for r in db.query(TxnPayment).filter_by(txn_id=txn_id).all()])
        assert before == after, "slices should not be touched when only customer changes"
