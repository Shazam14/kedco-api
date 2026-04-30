"""
Phase 5 — BUY-side splits + BUY payment-status concept.

Pre-Phase-5: every BUY auto-RECEIVED on submit; SPLIT toggle was SELL-only.
Phase 5 lifts the gate: BUY accepts payments[], pending BUY slices stay PENDING
until treasurer confirms, and rider non-CASH BUY slices force PENDING (rider
gave the customer a promise, not the cash).

Locked rules covered here:
  • Counter BUY accepts payments[] like SELL did.
  • Counter BUY can mark a slice PENDING explicitly (e.g. "we'll wire the customer
    later"); status is respected.
  • Rider non-CASH BUY slices forced PENDING regardless of client (parity with
    rider non-CASH SELL).
  • Rider cash-out-of-pocket BUY = RECEIVED (rider already paid).
  • confirm-payment on BUY flips parent + every still-pending slice.
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


class TestCounterBuyAcceptsSplits:
    def test_buy_two_slice_split_persists(self, client, cashier_user, usd_setup):
        # ₱5,700 BUY paid as ₱2,000 cash + ₱3,700 bank transfer to customer.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",          "amount_php": 2000.0},
                    {"method": "BANK_TRANSFER", "amount_php": 3700.0, "reference_no": "BT-001"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        slices = body["payments"]
        assert len(slices) == 2
        assert sum(s["amount_php"] for s in slices) == 5700.0
        assert {s["method"] for s in slices} == {"CASH", "BANK_TRANSFER"}
        bt = next(s for s in slices if s["method"] == "BANK_TRANSFER")
        assert bt["reference_no"] == "BT-001"

    def test_buy_pending_slice_respects_client(self, client, cashier_user, usd_setup):
        # Cashier explicitly marks the bank-transfer slice as PENDING (we owe customer).
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",          "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "BANK_TRANSFER", "amount_php": 3700.0, "status": "PENDING"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        cash = next(s for s in body["payments"] if s["method"] == "CASH")
        bt   = next(s for s in body["payments"] if s["method"] == "BANK_TRANSFER")
        assert cash["status"] == "RECEIVED"
        assert bt["status"]   == "PENDING"
        assert body["payment_status"] == "PENDING"

    def test_buy_sum_mismatch_returns_400(self, client, cashier_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",          "amount_php": 2000.0},
                    {"method": "BANK_TRANSFER", "amount_php": 1000.0},  # short ₱2,700
                ],
            },
        )
        assert r.status_code == 400
        assert "does not match" in r.json()["detail"]


class TestRiderBuyForcesNonCashPending:
    """Rider non-CASH BUY slice = "we still owe the customer". Force PENDING
    until treasurer wires the money. Cash-out-of-pocket = RECEIVED."""
    def test_rider_buy_cash_plus_bank_transfer(self, client, rider_user, usd_setup):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "ridertest",
                "payments": [
                    {"method": "CASH",          "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "BANK_TRANSFER", "amount_php": 3700.0, "status": "RECEIVED"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        cash = next(s for s in body["payments"] if s["method"] == "CASH")
        bt   = next(s for s in body["payments"] if s["method"] == "BANK_TRANSFER")
        assert cash["status"] == "RECEIVED"
        assert bt["status"]   == "PENDING"  # forced regardless of client input
        assert body["payment_status"] == "PENDING"

    def test_rider_buy_all_cash_stays_received(self, client, rider_user, usd_setup):
        # Rider hands customer the whole amount in cash → fully received.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "ridertest",
                "payment_mode": "CASH",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["payment_status"] == "RECEIVED"
        assert body["payments"][0]["status"] == "RECEIVED"


class TestConfirmPaymentOnBuy:
    def test_confirm_flips_buy_parent_and_pending_slices(self, client, cashier_user, usd_setup):
        create = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "cashiertest",
                "payments": [
                    {"method": "CASH",          "amount_php": 2000.0, "status": "RECEIVED"},
                    {"method": "BANK_TRANSFER", "amount_php": 3700.0, "status": "PENDING"},
                ],
            },
        )
        assert create.status_code == 201
        txn_id = create.json()["id"]
        assert create.json()["payment_status"] == "PENDING"

        confirm = client.patch(
            f"/api/v1/rider/transactions/{txn_id}/confirm-payment",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert confirm.status_code == 200, confirm.text

        today = client.get(
            "/api/v1/transactions/today",
            headers=auth_header("admintest", "admin"),
        )
        assert today.status_code == 200
        row = next(t for t in today.json() if t["id"] == txn_id)
        assert row["payment_status"] == "RECEIVED"
        assert all(s["status"] == "RECEIVED" for s in row["payments"])
        cash = next(s for s in row["payments"] if s["method"] == "CASH")
        bt   = next(s for s in row["payments"] if s["method"] == "BANK_TRANSFER")
        assert cash["confirmed_by"] == "cashiertest"
        assert bt["confirmed_by"]   == "supervisortest"
