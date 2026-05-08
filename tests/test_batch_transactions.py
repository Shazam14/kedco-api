"""
POST /transactions/batch — multi-currency same-customer batch.
Cashier path was pre-existing; rider path added 2026-05-08 so a rider can
record one customer's USD + JPY + EUR conversions in a single submit
instead of three separate calls + a post-hoc LINK CUSTOMER step.
"""
import pytest
from tests.conftest import auth_header


@pytest.fixture
def two_ccy_setup(db):
    from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition
    from app.core.today import get_today
    today = get_today()
    db.add(Currency(code="USD", name="US Dollar", flag="🇺🇸", category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y"))
    db.add(Currency(code="JPY", name="Japanese Yen", flag="🇯🇵", category=CurrencyCategory.MAIN, decimal_places=2, sort_order=2, is_active="Y"))
    db.add(DailyRate(date=today, currency_code="USD", buy_rate=57.0, sell_rate=58.0, set_by="admintest"))
    db.add(DailyRate(date=today, currency_code="JPY", buy_rate=0.37, sell_rate=0.38, set_by="admintest"))
    db.add(DailyPosition(date=today, currency_code="USD", carry_in_qty=10_000.0, carry_in_rate=57.5))
    db.add(DailyPosition(date=today, currency_code="JPY", carry_in_qty=500_000.0, carry_in_rate=0.37))
    db.commit()


class TestRiderBatch:
    def test_rider_can_submit_batch(self, client, rider_user, two_ccy_setup):
        r = client.post(
            "/api/v1/transactions/batch",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "BUY",
                "source": "RIDER",
                "customer": "Mark R.",
                "payment_mode": "CASH",
                "items": [
                    {"currency": "USD", "foreign_amt": 100, "rate": 57.0},
                    {"currency": "JPY", "foreign_amt": 10_000, "rate": 0.37},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body) == 2
        assert {b["currency"] for b in body} == {"USD", "JPY"}
        # All share the same batch_id
        assert len({b["batch_id"] for b in body}) == 1
        # Rider source uses RD- prefix
        assert all(b["id"].startswith("RD-") for b in body)
        # CASH → RECEIVED
        assert all(b["payment_status"] == "RECEIVED" for b in body)

    def test_rider_batch_non_cash_forces_pending(self, client, rider_user, two_ccy_setup):
        r = client.post(
            "/api/v1/transactions/batch",
            headers=auth_header("ridertest", "rider"),
            json={
                "type": "SELL",
                "source": "RIDER",
                "customer": "Mark R.",
                "payment_mode": "GCASH",
                "items": [
                    {"currency": "USD", "foreign_amt": 50, "rate": 58.0},
                ],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body[0]["payment_status"] == "PENDING"
        assert body[0]["payments"][0]["status"] == "PENDING"

    def test_cashier_batch_still_uses_or_prefix(self, client, cashier_user, two_ccy_setup):
        # Regression: pre-existing cashier behavior unchanged.
        r = client.post(
            "/api/v1/transactions/batch",
            headers=auth_header("cashiertest", "cashier"),
            json={
                "type": "BUY",
                "source": "COUNTER",
                "customer": "Walk-in",
                "payment_mode": "CASH",
                "items": [{"currency": "USD", "foreign_amt": 100, "rate": 57.0}],
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()[0]["id"].startswith("OR-")
