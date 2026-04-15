"""
Unit tests for teller shift business logic.

These tests cover the expected cash calculation formula and edge cases
without touching the database. The formula:

    expected_closing_cash = opening_cash + Σ(SELL php_amt) - Σ(BUY php_amt)

Logic rationale:
    BUY  → Kedco pays PHP out to customer  → drawer decreases
    SELL → Kedco receives PHP from customer → drawer increases
"""

import pytest


def compute_expected_cash(
    opening_cash: float,
    transactions: list[dict],  # list of {type: 'BUY'|'SELL', php_amt: float}
) -> float:
    """
    Pure Python version of the shift close expected cash formula.
    Mirrors what shifts.py does when closing a shift.
    """
    total_sold   = sum(t["php_amt"] for t in transactions if t["type"] == "SELL")
    total_bought = sum(t["php_amt"] for t in transactions if t["type"] == "BUY")
    return round(opening_cash + total_sold - total_bought, 2)


def compute_variance(closing_cash: float, expected_cash: float) -> float:
    return round(closing_cash - expected_cash, 2)


# ─── Expected Cash Formula ─────────────────────────────────────────────────────

class TestExpectedCash:

    def test_no_transactions(self):
        """No transactions — expected equals opening."""
        result = compute_expected_cash(10_000.0, [])
        assert result == pytest.approx(10_000.0)

    def test_sells_increase_drawer(self):
        """SELL = customer gives PHP to Kedco. Drawer grows."""
        txns = [
            {"type": "SELL", "php_amt": 5_800.0},
            {"type": "SELL", "php_amt": 11_600.0},
        ]
        # 10000 + 5800 + 11600 = 27400
        assert compute_expected_cash(10_000.0, txns) == pytest.approx(27_400.0)

    def test_buys_decrease_drawer(self):
        """BUY = Kedco pays PHP to customer. Drawer shrinks."""
        txns = [
            {"type": "BUY", "php_amt": 5_700.0},
            {"type": "BUY", "php_amt": 2_850.0},
        ]
        # 10000 - 5700 - 2850 = 1450
        assert compute_expected_cash(10_000.0, txns) == pytest.approx(1_450.0)

    def test_mixed_transactions(self):
        """Realistic shift: some buys, some sells."""
        txns = [
            {"type": "BUY",  "php_amt": 58_000.0},   # customer sold 1000 USD
            {"type": "SELL", "php_amt": 29_000.0},   # customer bought 500 USD
            {"type": "BUY",  "php_amt": 11_400.0},   # customer sold 200 KRW equiv
            {"type": "SELL", "php_amt": 17_400.0},   # customer bought 300 KRW equiv
        ]
        # opening + SELLs - BUYs = 50000 + (29000+17400) - (58000+11400)
        # = 50000 + 46400 - 69400 = 27000
        assert compute_expected_cash(50_000.0, txns) == pytest.approx(27_000.0)

    def test_zero_opening_cash(self):
        """Cashier with no opening float (e.g. first shift on Day 1)."""
        txns = [{"type": "SELL", "php_amt": 5_800.0}]
        assert compute_expected_cash(0.0, txns) == pytest.approx(5_800.0)

    def test_rounding_to_two_decimals(self):
        """PHP amounts always round to 2 decimal places."""
        txns = [
            {"type": "SELL", "php_amt": 1234.567},
            {"type": "BUY",  "php_amt": 567.891},
        ]
        result = compute_expected_cash(1000.0, txns)
        # raw: 1000 + 1234.567 - 567.891 = 1666.676 → rounds to 1666.68
        assert result == pytest.approx(1666.68, abs=0.005)


# ─── Variance ─────────────────────────────────────────────────────────────────

class TestShiftVariance:

    def test_zero_variance(self):
        """Cashier counted correctly — no discrepancy."""
        assert compute_variance(27_000.0, 27_000.0) == 0.0

    def test_positive_variance_overage(self):
        """Cashier has more cash than expected — rare but possible (e.g. customer left money)."""
        assert compute_variance(27_100.0, 27_000.0) == pytest.approx(100.0)

    def test_negative_variance_shortage(self):
        """Cashier is short — common flag for investigation."""
        assert compute_variance(26_800.0, 27_000.0) == pytest.approx(-200.0)

    def test_small_rounding_variance(self):
        """Sub-peso variance from rounding — should still be captured precisely."""
        assert compute_variance(27_000.50, 27_000.0) == pytest.approx(0.50)


# ─── Shift State Logic ────────────────────────────────────────────────────────

class TestShiftStateRules:
    """
    Tests for the rules enforced by the shift endpoints.
    These mirror the guard conditions in app/api/v1/shifts.py.
    """

    def test_cannot_open_two_shifts_same_day(self):
        """Simulate: cashier already has an open shift → should block."""
        open_shifts_today = [{"cashier": "cashier1", "status": "OPEN"}]

        def try_open(cashier: str, existing: list[dict]) -> str:
            already_open = any(
                s["cashier"] == cashier and s["status"] == "OPEN"
                for s in existing
            )
            if already_open:
                return "CONFLICT: already have an open shift"
            return "OK"

        assert try_open("cashier1", open_shifts_today) == "CONFLICT: already have an open shift"
        assert try_open("cashier2", open_shifts_today) == "OK"

    def test_cannot_close_without_open_shift(self):
        """Simulate: no open shift to close → should 404."""
        open_shifts_today = []

        def try_close(cashier: str, existing: list[dict]) -> str:
            shift = next(
                (s for s in existing if s["cashier"] == cashier and s["status"] == "OPEN"),
                None,
            )
            if not shift:
                return "NOT FOUND"
            return "CLOSED"

        assert try_close("cashier1", open_shifts_today) == "NOT FOUND"

    def test_different_cashiers_can_open_shifts_simultaneously(self):
        """Multiple cashiers working at the same time is valid."""
        open_shifts_today = [
            {"cashier": "cashier1", "status": "OPEN"},
            {"cashier": "cashier2", "status": "OPEN"},
        ]

        def is_blocked(cashier: str, existing: list[dict]) -> bool:
            return any(
                s["cashier"] == cashier and s["status"] == "OPEN"
                for s in existing
            )

        assert not is_blocked("cashier3", open_shifts_today)
        assert is_blocked("cashier1", open_shifts_today)
