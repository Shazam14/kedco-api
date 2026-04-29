"""
Daily report — PENDING SELL stock-deduction guarantee.

Captured 2026-04-29 from rider04 RD-1C31DD20 on April 23: a BANK_TRANSFER SELL
of USD 1,610 was force-PENDING by the rider non-cash rule. The old report code
skipped PENDING entirely, so the stock_summary closing_qty was 1,610 too high
(the USD was physically handed to the customer; only the PHP receivable hadn't
cleared). Stock decrements on physical handover regardless of payment status.

PHP/THAN accrual behaviour (PENDING included in totals + surfaced via
*_pending fields) is tested separately in test_report_accrual_with_pending_badge.
"""
import pytest
from app.core.today import get_today
from tests.conftest import auth_header

# Pass explicit ?date= so the report's `date.today()` default doesn't drift
# from the mock-date conftest seeds against.
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


class TestPendingSellDeductsStockButNotPhp:
    def test_pending_sell_deducts_sell_qty(
        self, client, admin_user, rider_user, usd_setup, make_transaction
    ):
        # One RECEIVED cash sell + one PENDING bank-transfer sell.
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

        usd_stock = _by_code(body["stock_summary"], "USD")
        assert usd_stock is not None, "USD missing from stock_summary"
        # Both SELLs deduct: 2,000 + 1,610 = 3,610
        assert usd_stock["sell_qty"] == pytest.approx(3_610.0)
        # carry 10,000 − 3,610 sold = 6,390
        assert usd_stock["closing_qty"] == pytest.approx(6_390.0)

    def test_pending_only_currency_still_appears_in_stock_summary(
        self, client, admin_user, rider_user, usd_setup, make_transaction
    ):
        # Edge case: a currency whose ONLY today txn is PENDING. The old code
        # would skip it entirely from by_currency, so stock_summary used 0 for
        # sell_qty even though the FX was physically out the door.
        make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            currency="USD", foreign_amt=500, rate=60.5, php_amt=30_250, than=500,
            payment_status="PENDING",
        )

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        body = r.json()

        usd_stock = _by_code(body["stock_summary"], "USD")
        assert usd_stock["sell_qty"]   == pytest.approx(500.0)
        assert usd_stock["closing_qty"] == pytest.approx(9_500.0)  # 10,000 − 500
