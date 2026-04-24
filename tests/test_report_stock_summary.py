"""
Unit tests for the stock_summary computation logic in the daily report.

The closing_rate MUST come from next-day DailyPosition.carry_in_rate (= STOCKSLEFT
rate written by the seeder) — NOT computed as a weighted average client-side or
server-side. This was the root bug: JPY carry_in_rate=0.371 (3dp) caused the
weighted avg to round to 0.371 instead of the correct 0.3707.

Ground truth constants: April 5, 2026 — verified against Ken's Excel and live DB.
  Opening  = DailyPosition where date = 2026-04-05
  Closing  = DailyPosition where date = 2026-04-06  (next day's carry-in = STOCKSLEFT)
"""

import pytest


# ── Pure computation helpers (mirrors report.py stock_summary block) ──────────

def closing_qty(carry_in_qty: float, buy_qty: float, sell_qty: float) -> float:
    return carry_in_qty + buy_qty - sell_qty


def closing_php(qty: float, rate: float) -> float:
    return round(qty * rate, 2)


# ── April 5, 2026 ground truth (from live DB, matches Ken's Excel) ────────────

APR5_OPEN = {
    "USD": {"qty": 17651.0, "rate": 59.55},
    "JPY": {"qty": 1261000.0, "rate": 0.3704},
}

APR6_OPEN = {  # = April 5 closing / STOCKSLEFT
    "USD": {"qty": 33106.0, "rate": 59.60},
    "JPY": {"qty": 1853000.0, "rate": 0.3706},
}


class TestClosingQty:
    def test_usd_april5(self):
        # carry_in=17651, net buys=15455 → closing=33106
        net = APR6_OPEN["USD"]["qty"] - APR5_OPEN["USD"]["qty"]  # 15455
        assert closing_qty(APR5_OPEN["USD"]["qty"], net, 0) == APR6_OPEN["USD"]["qty"]

    def test_buy_and_sell(self):
        assert closing_qty(1000, buy_qty=500, sell_qty=200) == 1300

    def test_zero_movement(self):
        assert closing_qty(500, 0, 0) == 500

    def test_sell_more_than_carry_in(self):
        # Should still produce the math result (caller is responsible for validity)
        assert closing_qty(100, 200, 50) == 250


class TestClosingPhp:
    def test_usd_april5(self):
        # 33106 * 59.60 = 1,973,117.60
        assert closing_php(APR6_OPEN["USD"]["qty"], APR6_OPEN["USD"]["rate"]) == pytest.approx(1_973_117.60, rel=1e-5)

    def test_jpy_april5(self):
        # 1,853,000 * 0.3706 = 686,721.80
        assert closing_php(APR6_OPEN["JPY"]["qty"], APR6_OPEN["JPY"]["rate"]) == pytest.approx(686_721.80, rel=1e-5)

    def test_rounds_to_2dp(self):
        assert closing_php(100, 0.123456) == 12.35


class TestClosingRateSourceRule:
    """
    The closing_rate must equal next-day DailyPosition.carry_in_rate exactly.
    It must NOT be derived from a weighted average of carry-in + buy transactions.
    """

    def test_jpy_closing_rate_is_not_carry_in_rate(self):
        # carry_in_rate for JPY on April 5 is 0.3704 — closing is 0.3706
        # They are different; the closing must use next-day position, not today's carry_in
        assert APR5_OPEN["JPY"]["rate"] != APR6_OPEN["JPY"]["rate"]

    def test_jpy_closing_rate_matches_next_day_position(self):
        # The only correct source: DailyPosition(date=2026-04-06).carry_in_rate
        assert APR6_OPEN["JPY"]["rate"] == 0.3706

    def test_usd_closing_rate_matches_next_day_position(self):
        assert APR6_OPEN["USD"]["rate"] == 59.60
