"""
Unit tests for the core FX business logic in services/forex.py.
These tests are pure Python — no database, no HTTP, no fixtures.
"""

import pytest
from app.services.forex import compute_position, compute_than, CarryIn, TodayBuy


# ─── compute_position ─────────────────────────────────────────────────────────

class TestComputePosition:
    """Ken's per-day averaging rule — each scenario mirrors a real Kedco situation."""

    def test_carry_in_only_no_buys(self):
        """Just carry-in stock, no buys today. Daily avg = carry-in rate."""
        result = compute_position(
            carry_in=CarryIn(qty=1000, rate=57.50),
            today_buys=[],
            today_sell_rate=58.00,
        )
        assert result.total_qty == 1000
        assert result.daily_avg_cost == pytest.approx(57.50)
        assert result.today_gain_per_unit == pytest.approx(0.50)
        assert result.unrealized_php == pytest.approx(500.0)

    def test_carry_in_plus_one_buy(self):
        """Ken's confirmed example: 1000 USD @ 57.50 carry-in + 500 USD @ 57.00 buy = 57.33 avg."""
        result = compute_position(
            carry_in=CarryIn(qty=1000, rate=57.50),
            today_buys=[TodayBuy(qty=500, rate=57.00)],
            today_sell_rate=58.00,
        )
        assert result.total_qty == 1500
        # (1000*57.50 + 500*57.00) / 1500 = (57500 + 28500) / 1500 = 86000 / 1500 = 57.333...
        assert result.daily_avg_cost == pytest.approx(57.333, rel=1e-3)
        assert result.today_gain_per_unit == pytest.approx(58.00 - 57.333, rel=1e-3)

    def test_carry_in_plus_multiple_buys(self):
        """Multiple buys today blended with carry-in — only today's rates count."""
        result = compute_position(
            carry_in=CarryIn(qty=500, rate=57.00),
            today_buys=[
                TodayBuy(qty=200, rate=57.20),
                TodayBuy(qty=300, rate=56.80),
            ],
            today_sell_rate=58.00,
        )
        # total = 1000 units
        # cost = 500*57 + 200*57.20 + 300*56.80 = 28500 + 11440 + 17040 = 56980
        # avg = 56980 / 1000 = 56.98
        assert result.total_qty == 1000
        assert result.daily_avg_cost == pytest.approx(56.98)

    def test_no_stock_at_all(self):
        """Zero carry-in, zero buys — no division by zero."""
        result = compute_position(
            carry_in=CarryIn(qty=0, rate=0),
            today_buys=[],
            today_sell_rate=58.00,
        )
        assert result.total_qty == 0
        assert result.daily_avg_cost == 0.0

    def test_previous_days_do_not_bleed(self):
        """
        Critical: yesterday's avg rate is the carry-in rate, not some accumulated value.
        Two runs with different carry-in rates give independent results.
        """
        # Day 1 result (carry-in from Day 0)
        day1 = compute_position(
            carry_in=CarryIn(qty=1000, rate=56.00),
            today_buys=[TodayBuy(qty=500, rate=57.00)],
            today_sell_rate=58.00,
        )
        # Day 2 starts fresh — carry-in rate = day1.daily_avg_cost
        day2 = compute_position(
            carry_in=CarryIn(qty=1000, rate=day1.daily_avg_cost),
            today_buys=[TodayBuy(qty=200, rate=57.50)],
            today_sell_rate=58.50,
        )
        # Day 2's avg is computed solely from its carry-in + today's buys
        expected_day2_cost = (1000 * day1.daily_avg_cost + 200 * 57.50) / 1200
        assert day2.daily_avg_cost == pytest.approx(expected_day2_cost, rel=1e-6)
        # Day 1's avg does NOT appear directly — only via carry-in rate
        assert day2.daily_avg_cost != day1.daily_avg_cost

    def test_stock_value_uses_sell_rate(self):
        """Stock value = total_qty × sell_rate, not avg cost."""
        result = compute_position(
            carry_in=CarryIn(qty=1000, rate=57.00),
            today_buys=[],
            today_sell_rate=59.00,
        )
        assert result.stock_value_php == pytest.approx(1000 * 59.00)

    def test_unrealized_php(self):
        """Unrealized = gain_per_unit × total_qty."""
        result = compute_position(
            carry_in=CarryIn(qty=1000, rate=57.00),
            today_buys=[],
            today_sell_rate=58.50,
        )
        assert result.unrealized_php == pytest.approx(1.50 * 1000)

    def test_small_currency_vnd(self):
        """VND-scale: rates < 1. Precision must hold at 4 decimals."""
        result = compute_position(
            carry_in=CarryIn(qty=5_000_000, rate=0.0022),
            today_buys=[TodayBuy(qty=2_000_000, rate=0.0021)],
            today_sell_rate=0.0023,
        )
        # avg = (5M*0.0022 + 2M*0.0021) / 7M = (11000 + 4200) / 7M = 15200/7000000
        assert result.total_qty == 7_000_000
        assert result.daily_avg_cost == pytest.approx(15200 / 7_000_000, rel=1e-6)

    def test_high_value_currency_kwd(self):
        """KWD-scale: rates ~140. Formula should be identical."""
        result = compute_position(
            carry_in=CarryIn(qty=100, rate=140.00),
            today_buys=[TodayBuy(qty=50, rate=141.00)],
            today_sell_rate=142.00,
        )
        # avg = (100*140 + 50*141) / 150 = (14000 + 7050) / 150 = 21050/150
        assert result.daily_avg_cost == pytest.approx(21050 / 150)


# ─── compute_than ─────────────────────────────────────────────────────────────

class TestComputeThan:
    """THAN = (sell_rate - daily_avg_cost) × units_sold"""

    def test_basic_than(self):
        assert compute_than(58.00, 57.00, 100) == pytest.approx(100.0)

    def test_than_zero_when_sell_equals_avg(self):
        assert compute_than(57.00, 57.00, 500) == pytest.approx(0.0)

    def test_than_negative_on_loss(self):
        """Selling below avg cost — negative THAN (loss). Should be allowed."""
        assert compute_than(56.00, 57.00, 200) == pytest.approx(-200.0)

    def test_than_fractional_rates(self):
        """VND-level precision."""
        assert compute_than(0.0023, 0.0021, 1_000_000) == pytest.approx(200.0, rel=1e-6)
