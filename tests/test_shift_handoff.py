"""
Tests for the shift handoff pre-fill on /treasurer/pending-float.

When Cashier 1 closes and Cashier 2 opens on the same terminal, the
pending-float endpoint should return Cashier 1's closing_cash_php so
the opening form is pre-populated automatically (no supervisor action needed).
"""
import pytest
from datetime import datetime, timezone

from app.models.shift import TellerShift, ShiftStatus, TreasurerFloat
from app.core.today import get_today
from tests.conftest import auth_header


def _make_closed_shift(db, *, cashier: str, cashier_name: str, terminal_id: str,
                       closing_cash_php: float, expected_cash_php: float = None):
    today = get_today()
    shift = TellerShift(
        date=today,
        cashier=cashier,
        cashier_name=cashier_name,
        status=ShiftStatus.CLOSED,
        opening_cash_php=900_000,
        closing_cash_php=closing_cash_php,
        expected_cash_php=expected_cash_php or closing_cash_php,
        terminal_id=terminal_id,
        opened_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


class TestHandoffPreFill:

    def test_returns_closing_cash_when_prev_shift_on_same_terminal(
        self, client, db, cashier_user, admin_user
    ):
        _make_closed_shift(
            db, cashier="cashiertest", cashier_name="Cashier Test",
            terminal_id="Counter 1", closing_cash_php=310_975,
        )
        # A different cashier asks for pending-float on the same terminal
        r = client.get(
            "/api/v1/treasurer/pending-float?terminal_id=Counter+1",
            headers=auth_header("cashiertest2", "cashier"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["amount_php"] == 310_975
        assert body["source"] == "handoff"
        assert body["cashier_name"] == "Cashier Test"

    def test_treasurer_float_takes_priority_over_handoff(
        self, client, db, cashier_user, admin_user
    ):
        # Both a TreasurerFloat and a prev closed shift exist
        _make_closed_shift(
            db, cashier="other", cashier_name="Other Cashier",
            terminal_id="Counter 1", closing_cash_php=310_975,
        )
        today = get_today()
        tf = TreasurerFloat(
            date=today,
            cashier_username="cashiertest",
            treasurer_username="admintest",
            amount_php=900_000,
        )
        db.add(tf)
        db.commit()

        r = client.get(
            "/api/v1/treasurer/pending-float?terminal_id=Counter+1",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["amount_php"] == 900_000
        assert body["source"] == "treasurer"

    def test_returns_null_when_no_float_and_no_prev_shift(
        self, client, db, cashier_user
    ):
        r = client.get(
            "/api/v1/treasurer/pending-float?terminal_id=Counter+1",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 200
        assert r.json() is None

    def test_returns_null_without_terminal_id_and_no_float(
        self, client, db, cashier_user
    ):
        # No terminal_id passed — can't do handoff lookup, no float either
        r = client.get(
            "/api/v1/treasurer/pending-float",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 200
        assert r.json() is None

    def test_open_shift_on_same_terminal_ignored(
        self, client, db, cashier_user
    ):
        # OPEN shift on same terminal should NOT be used as handoff
        today = get_today()
        shift = TellerShift(
            date=today,
            cashier="other",
            cashier_name="Other Cashier",
            status=ShiftStatus.OPEN,
            opening_cash_php=900_000,
            terminal_id="Counter 1",
            opened_at=datetime.now(timezone.utc),
        )
        db.add(shift)
        db.commit()

        r = client.get(
            "/api/v1/treasurer/pending-float?terminal_id=Counter+1",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 200
        assert r.json() is None

    def test_different_terminal_not_used(
        self, client, db, cashier_user
    ):
        # Closed shift on Counter 2 should not pre-fill for Counter 1
        _make_closed_shift(
            db, cashier="other", cashier_name="Other Cashier",
            terminal_id="Counter 2", closing_cash_php=310_975,
        )
        r = client.get(
            "/api/v1/treasurer/pending-float?terminal_id=Counter+1",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 200
        assert r.json() is None
