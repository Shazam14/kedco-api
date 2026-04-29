"""
Daily report — ACCRUAL totals + PENDING receivables badge fields.

Spec finalized 2026-04-29 with Ken: the daily report is a closing statement.
TOTAL SOLD and TOTAL THAN must include PENDING SELLs so they match Excel's
GRAND TOTAL SOLD / GRAND TOTAL THAN. To keep receivables visible without
filtering, the API surfaces PENDING amounts separately as *_pending fields
that the frontend renders as a "[⏳ pending: ₱X]" badge alongside each total.

BUY total stays RECEIVED-only — PENDING BUY is rare and means we owe the
customer. Per-cashier remains RECEIVED-only too (it's a cash-flow view).
"""
import pytest
from app.core.today import get_today
from tests.conftest import auth_header

TODAY_ISO = get_today().isoformat()


@pytest.fixture
def usd_setup(db):
    from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(DailyRate(
        date=get_today(), currency_code="USD",
        buy_rate=60.0, sell_rate=60.5, set_by="admintest",
    ))
    db.add(DailyPosition(
        date=get_today(), currency_code="USD",
        carry_in_qty=10_000.0, carry_in_rate=59.5,
    ))
    db.commit()


def _by_code(items, code):
    return next((x for x in items if x["code"] == code), None)


class TestAccrualTotalsIncludePending:
    def test_top_level_total_sold_is_accrual(
        self, client, admin_user, rider_user, usd_setup, make_transaction
    ):
        make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            currency="USD", foreign_amt=2_000, rate=60.3, php_amt=120_600, than=3_257.04,
            payment_status="RECEIVED",
        )
        make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            currency="USD", foreign_amt=1_610, rate=60.5, php_amt=97_405, than=2_943.91,
            payment_status="PENDING",
        )

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        body = r.json()

        # Accrual: RECEIVED 120,600 + PENDING 97,405 = 218,005
        assert body["total_sold_php"] == pytest.approx(218_005.0)
        assert body["total_than"]     == pytest.approx(6_200.95)

        # Pending fields surface the receivables piece separately
        assert body["total_sold_php_pending"] == pytest.approx(97_405.0)
        assert body["total_than_pending"]     == pytest.approx(2_943.91)
        assert body["pending_count"] == 1

    def test_per_currency_is_accrual_with_pending_split(
        self, client, admin_user, rider_user, usd_setup, make_transaction
    ):
        make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            currency="USD", foreign_amt=2_000, rate=60.3, php_amt=120_600, than=3_257.04,
            payment_status="RECEIVED",
        )
        make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            currency="USD", foreign_amt=1_610, rate=60.5, php_amt=97_405, than=2_943.91,
            payment_status="PENDING",
        )

        body = client.get(
            f"/api/v1/report/daily?date={TODAY_ISO}",
            headers=auth_header("admintest", "admin"),
        ).json()

        usd = _by_code(body["by_currency"], "USD")
        assert usd is not None
        # Accrual sums
        assert usd["sell_php"] == pytest.approx(218_005.0)
        assert usd["than"]     == pytest.approx(6_200.95)
        # Pending split
        assert usd["sell_php_pending"] == pytest.approx(97_405.0)
        assert usd["than_pending"]     == pytest.approx(2_943.91)

    def test_no_pending_keeps_zero_pending_fields(
        self, client, admin_user, cashier_user, usd_setup, make_transaction
    ):
        make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=60.5, php_amt=6_050, than=100,
            payment_status="RECEIVED",
        )

        body = client.get(
            f"/api/v1/report/daily?date={TODAY_ISO}",
            headers=auth_header("admintest", "admin"),
        ).json()

        assert body["total_sold_php"] == pytest.approx(6_050.0)
        assert body["total_sold_php_pending"] == pytest.approx(0.0)
        assert body["total_than_pending"]     == pytest.approx(0.0)
        assert body["pending_count"] == 0

        usd = _by_code(body["by_currency"], "USD")
        assert usd["sell_php_pending"] == pytest.approx(0.0)
        assert usd["than_pending"]     == pytest.approx(0.0)

    def test_buy_total_stays_received_only(
        self, client, admin_user, cashier_user, usd_setup, make_transaction
    ):
        # PENDING BUY is rare (means we owe the customer). It should NOT
        # inflate total_bought_php — buys are a cash-out view.
        make_transaction(
            type="BUY", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=200, rate=60.0, php_amt=12_000, than=0,
            payment_status="RECEIVED",
        )
        make_transaction(
            type="BUY", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=50, rate=60.0, php_amt=3_000, than=0,
            payment_status="PENDING",
        )

        body = client.get(
            f"/api/v1/report/daily?date={TODAY_ISO}",
            headers=auth_header("admintest", "admin"),
        ).json()

        assert body["total_bought_php"] == pytest.approx(12_000.0)
        usd = _by_code(body["by_currency"], "USD")
        assert usd["buy_php"] == pytest.approx(12_000.0)
