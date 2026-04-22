"""
Unit tests for commission logic — both BUY and SELL.

Commission is the spread between cashier rate and official (admin-set) rate:
  SELL: (cashier_rate - official_sell_rate) × qty   → positive when cashier charged more
  BUY:  (official_buy_rate - cashier_rate)  × qty   → positive when cashier paid less

These are pure-Python tests — no DB, no HTTP.
"""

import pytest


def compute_commission(txn_type: str, cashier_rate: float, official_rate: float, qty: float) -> float:
    if txn_type == "SELL":
        return (cashier_rate - official_rate) * qty
    else:  # BUY
        return (official_rate - cashier_rate) * qty


def split_commission(commission: float, referrer: str | None):
    if referrer:
        return commission / 2, commission / 2   # cashier, referrer
    return commission, 0.0


class TestSellCommission:
    def test_sell_above_official_earns_commission(self):
        comm = compute_commission("SELL", cashier_rate=57.50, official_rate=57.00, qty=1000)
        assert comm == pytest.approx(500.0)

    def test_sell_at_official_zero_commission(self):
        comm = compute_commission("SELL", cashier_rate=57.00, official_rate=57.00, qty=1000)
        assert comm == pytest.approx(0.0)

    def test_sell_below_official_negative_commission(self):
        comm = compute_commission("SELL", cashier_rate=56.50, official_rate=57.00, qty=1000)
        assert comm == pytest.approx(-500.0)

    def test_sell_commission_with_referrer_splits_50_50(self):
        comm = compute_commission("SELL", cashier_rate=57.50, official_rate=57.00, qty=1000)
        cashier_cut, referrer_cut = split_commission(comm, referrer="Juan dela Cruz")
        assert cashier_cut == pytest.approx(250.0)
        assert referrer_cut == pytest.approx(250.0)

    def test_sell_commission_no_referrer_all_to_cashier(self):
        comm = compute_commission("SELL", cashier_rate=57.50, official_rate=57.00, qty=1000)
        cashier_cut, referrer_cut = split_commission(comm, referrer=None)
        assert cashier_cut == pytest.approx(500.0)
        assert referrer_cut == pytest.approx(0.0)


class TestBuyCommission:
    def test_buy_below_official_earns_commission(self):
        """Cashier buys USD at 55.00 when official buy rate is 55.50 — Kedco saves ₱0.50/unit."""
        comm = compute_commission("BUY", cashier_rate=55.00, official_rate=55.50, qty=500)
        assert comm == pytest.approx(250.0)

    def test_buy_at_official_zero_commission(self):
        comm = compute_commission("BUY", cashier_rate=55.50, official_rate=55.50, qty=500)
        assert comm == pytest.approx(0.0)

    def test_buy_above_official_negative_commission(self):
        """Cashier overpays — negative commission (Kedco loses)."""
        comm = compute_commission("BUY", cashier_rate=56.00, official_rate=55.50, qty=500)
        assert comm == pytest.approx(-250.0)

    def test_buy_commission_with_referrer_splits_50_50(self):
        comm = compute_commission("BUY", cashier_rate=55.00, official_rate=55.50, qty=1000)
        cashier_cut, referrer_cut = split_commission(comm, referrer="Tour Guide A")
        assert cashier_cut == pytest.approx(250.0)
        assert referrer_cut == pytest.approx(250.0)


class TestCommissionEdgeCases:
    def test_zero_qty(self):
        assert compute_commission("SELL", 57.50, 57.00, 0) == pytest.approx(0.0)

    def test_fractional_qty(self):
        """KWD uses 3 decimal places — fractional amounts must work."""
        comm = compute_commission("SELL", cashier_rate=140.00, official_rate=139.50, qty=0.500)
        assert comm == pytest.approx(0.25)

    def test_high_volume(self):
        comm = compute_commission("SELL", cashier_rate=57.10, official_rate=57.00, qty=100_000)
        assert comm == pytest.approx(10_000.0)
