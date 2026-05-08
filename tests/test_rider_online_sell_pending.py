"""
Rider sells paid via online channels (GCash, bank transfer, etc.) must be
marked PENDING regardless of what the client sent — the rider doesn't
physically have that PHP yet, so it shouldn't inflate in-hand totals. The
treasurer/admin clears it via the existing confirm-payment flow.

Cashier counter sells (face-to-face GCash) keep RECEIVED, since the cashier
verifies the payment on the spot before recording.
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
        carry_in_qty=1000.0, carry_in_rate=57.5,
    ))
    db.commit()


class TestRiderOnlineSellForcedPending:
    def test_rider_bank_transfer_sell_is_pending_even_if_client_sends_received(
        self, client, rider_user, make_dispatch, usd_setup
    ):
        make_dispatch()
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "SELL", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "ridertest",
                "payment_mode": "BANK_TRANSFER",
                "payment_status": "RECEIVED",  # client lies — server must override
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "PENDING"

    def test_rider_gcash_sell_is_pending(self, client, rider_user, make_dispatch, usd_setup):
        make_dispatch()
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "SELL", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "ridertest",
                "payment_mode": "GCASH",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "PENDING"

    def test_rider_cash_sell_stays_received(self, client, rider_user, make_dispatch, usd_setup):
        make_dispatch()
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "SELL", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "ridertest",
                "payment_mode": "CASH",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "RECEIVED"

    def test_rider_buy_with_bank_transfer_forced_pending(self, client, rider_user, make_dispatch, usd_setup):
        make_dispatch()
        # Phase 5: rider non-CASH BUY = "we still owe the customer" until treasurer
        # wires it. Force PENDING regardless of client. Mirrors the SELL-side rule.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY", "source": "RIDER", "currency": "USD",
                "foreign_amt": 100, "rate": 57.0, "cashier": "ridertest",
                "payment_mode": "BANK_TRANSFER",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "PENDING"

    def test_cashier_counter_bank_transfer_sell_stays_received(
        self, client, cashier_user, usd_setup
    ):
        # Cashier verifies payment on the spot — RECEIVED stays.
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "cashiertest",
                "payment_mode": "BANK_TRANSFER",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["payment_status"] == "RECEIVED"
