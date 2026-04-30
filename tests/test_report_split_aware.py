"""
Phase 4 — split-aware daily report.

What this guards:
  • PENDING is per-slice. A SELL with one CASH-RECEIVED + one GCASH-PENDING
    slice is half-pending, not all-pending. by_currency.sell_php_pending,
    than_pending, total_sold_php_pending, total_than_pending all reflect
    the slice-level pending share.
  • Each item in `transactions` carries its slices in a `payments[]` array
    so the frontend can render per-row breakdown.
  • New `by_payment_method` aggregate: one row per method, split by
    direction (BUY vs SELL), with received/pending split for SELL.
"""
import uuid
import pytest
from app.core.today import get_today
from app.models.transaction import TxnPayment, PaymentMode, PaymentStatus
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
        buy_rate=56.0, sell_rate=58.0, set_by="admintest",
    ))
    db.add(DailyPosition(
        date=get_today(), currency_code="USD",
        carry_in_qty=10_000.0, carry_in_rate=57.0,
    ))
    db.commit()


def _add_slices(db, txn_id, slices):
    """slices = [(method, amount_php, status, ref_no?)]"""
    for s in slices:
        method, amt, status = s[0], s[1], s[2]
        ref = s[3] if len(s) > 3 else None
        db.add(TxnPayment(
            id=uuid.uuid4(), txn_id=txn_id,
            method=PaymentMode(method), amount_php=amt,
            status=PaymentStatus(status), reference_no=ref,
        ))
    db.commit()


class TestPerSlicePendingMath:
    def test_half_paid_sell_pending_is_only_pending_slice(
        self, client, admin_user, usd_setup, make_transaction, db
    ):
        # ₱5,600 SELL: ₱2,000 CASH RECEIVED + ₱3,600 GCASH PENDING.
        # Parent.payment_status is PENDING (any slice pending), but only the
        # GCash slice should count as pending.
        txn = make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=56.0, php_amt=5600.0, than=50.0,
            payment_status="PENDING",
        )
        _add_slices(db, txn.id, [
            ("CASH",  2000.0, "RECEIVED"),
            ("GCASH", 3600.0, "PENDING", "GC-1"),
        ])

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        body = r.json()

        usd = next(c for c in body["by_currency"] if c["code"] == "USD")
        assert usd["sell_php"] == 5600.0  # accrual unchanged
        assert usd["sell_php_pending"] == 3600.0  # only GCash slice
        # than_pending = 50 × (3600/5600) = 32.142857... → rounds to 32.14
        assert round(usd["than_pending"], 2) == 32.14

        assert body["total_sold_php_pending"] == 3600.0
        assert round(body["total_than_pending"], 2) == 32.14
        assert body["pending_count"] == 1

    def test_fully_received_sell_has_zero_pending(
        self, client, admin_user, usd_setup, make_transaction, db
    ):
        txn = make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=56.0, php_amt=5600.0, than=50.0,
            payment_status="RECEIVED",
        )
        _add_slices(db, txn.id, [
            ("CASH",  2000.0, "RECEIVED"),
            ("GCASH", 3600.0, "RECEIVED", "GC-1"),
        ])

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        body = r.json()
        usd = next(c for c in body["by_currency"] if c["code"] == "USD")
        assert usd["sell_php_pending"] == 0.0
        assert usd["than_pending"] == 0.0
        assert body["pending_count"] == 0


class TestTransactionsCarrySlices:
    def test_each_txn_includes_payments_array(
        self, client, admin_user, usd_setup, make_transaction, db
    ):
        txn = make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=56.0, php_amt=5600.0, than=50.0,
            payment_status="PENDING",
        )
        _add_slices(db, txn.id, [
            ("CASH",  2000.0, "RECEIVED"),
            ("GCASH", 3600.0, "PENDING", "GC-1"),
        ])

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        body = r.json()
        item = next(t for t in body["transactions"] if t["id"] == txn.id)
        assert "payments" in item
        slices = item["payments"]
        assert len(slices) == 2
        cash = next(s for s in slices if s["method"] == "CASH")
        gcash = next(s for s in slices if s["method"] == "GCASH")
        assert cash["amount_php"] == 2000.0
        assert cash["status"] == "RECEIVED"
        assert gcash["amount_php"] == 3600.0
        assert gcash["status"] == "PENDING"
        assert gcash["reference_no"] == "GC-1"


class TestByPaymentMethodAggregate:
    def test_aggregates_slices_across_methods(
        self, client, admin_user, usd_setup, make_transaction, db
    ):
        # Txn A: ₱5,600 SELL — 2k CASH RECEIVED + 3.6k GCASH PENDING.
        a = make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=56.0, php_amt=5600.0, than=50.0,
            payment_status="PENDING",
        )
        _add_slices(db, a.id, [
            ("CASH",  2000.0, "RECEIVED"),
            ("GCASH", 3600.0, "PENDING", "GC-1"),
        ])
        # Txn B: ₱2,800 SELL — all CASH.
        b = make_transaction(
            type="SELL", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=50, rate=56.0, php_amt=2800.0, than=25.0,
            payment_status="RECEIVED",
        )
        _add_slices(db, b.id, [("CASH", 2800.0, "RECEIVED")])
        # Txn C: ₱5,700 BUY — all CASH (we paid customer).
        c = make_transaction(
            type="BUY", source="COUNTER", cashier="cashiertest",
            currency="USD", foreign_amt=100, rate=57.0, php_amt=5700.0, than=0.0,
            payment_status="RECEIVED",
        )
        _add_slices(db, c.id, [("CASH", 5700.0, "RECEIVED")])

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        body = r.json()
        bm = body["by_payment_method"]
        cash = next(m for m in bm if m["method"] == "CASH")
        gcash = next(m for m in bm if m["method"] == "GCASH")

        # CASH: 1 BUY slice (₱5,700) + 2 SELL slices (₱2,000 + ₱2,800 all received).
        assert cash["buy_count"] == 1
        assert cash["buy_php"]   == 5700.0
        assert cash["sell_count"] == 2
        assert cash["sell_php"]          == 4800.0
        assert cash["sell_php_received"] == 4800.0
        assert cash["sell_php_pending"]  == 0.0

        # GCASH: 0 BUYs, 1 SELL slice (₱3,600 PENDING).
        assert gcash["buy_count"] == 0
        assert gcash["sell_count"] == 1
        assert gcash["sell_php"]          == 3600.0
        assert gcash["sell_php_received"] == 0.0
        assert gcash["sell_php_pending"]  == 3600.0

    def test_empty_when_no_txns(self, client, admin_user, usd_setup):
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        body = r.json()
        assert body["by_payment_method"] == []
