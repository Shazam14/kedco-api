"""
Per-shift expense scoping.

Cashiers should only see expenses tied to their currently OPEN shift.
Once a shift closes, those rows disappear from the cashier's view.
Admin / supervisor always see everything.
"""
import pytest
from datetime import datetime, timezone

from app.models.shift import TellerShift, ShiftStatus
from app.core.today import get_today
from tests.conftest import auth_header


def _open_shift(db, username: str, full_name: str, opening: float = 100_000) -> TellerShift:
    s = TellerShift(
        date=get_today(),
        cashier=username,
        cashier_name=full_name,
        status=ShiftStatus.OPEN,
        opening_cash_php=opening,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _close_shift(db, shift: TellerShift, closing: float = 100_000):
    shift.status = ShiftStatus.CLOSED
    shift.closed_at = datetime.now(timezone.utc)
    shift.closing_cash_php = closing
    shift.expected_cash_php = closing
    shift.cash_variance = 0
    db.commit(); db.refresh(shift)


class TestExpensePost:

    def test_cashier_with_no_open_shift_blocked(self, client, cashier_user):
        r = client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS"},
        )
        assert r.status_code == 400
        assert "open a shift" in r.json()["detail"].lower()

    def test_cashier_post_stamps_current_shift(self, client, db, cashier_user):
        shift = _open_shift(db, "cashiertest", "Cashier Test")
        r = client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 250, "category": "MEALS"},
        )
        assert r.status_code == 201
        assert r.json()["shift_id"] == str(shift.id)

    def test_admin_can_post_without_open_shift(self, client, admin_user):
        r = client.post(
            "/api/v1/expenses/",
            headers=auth_header("admintest", "admin"),
            json={"amount_php": 100, "category": "MEALS"},
        )
        assert r.status_code == 201
        assert r.json()["shift_id"] is None


class TestExpenseGet:

    def test_cashier_sees_only_current_shift_rows(self, client, db, cashier_user):
        shift_a = _open_shift(db, "cashiertest", "Cashier Test")
        client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS", "description": "shift A meal"},
        )
        _close_shift(db, shift_a)

        shift_b = _open_shift(db, "cashiertest", "Cashier Test", opening=200_000)
        client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 200, "category": "MEALS", "description": "shift B meal"},
        )

        r = client.get("/api/v1/expenses/today", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["amount_php"] == 200
        assert rows[0]["shift_id"] == str(shift_b.id)

    def test_cashier_with_no_open_shift_sees_empty(self, client, db, cashier_user):
        shift = _open_shift(db, "cashiertest", "Cashier Test")
        client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS"},
        )
        _close_shift(db, shift)

        r = client.get("/api/v1/expenses/today", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 200
        assert r.json() == []

    def test_admin_sees_all_rows_across_shifts(self, client, db, admin_user, cashier_user):
        shift_a = _open_shift(db, "cashiertest", "Cashier Test")
        client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS"},
        )
        _close_shift(db, shift_a)

        _open_shift(db, "cashiertest", "Cashier Test", opening=200_000)
        client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 200, "category": "MEALS"},
        )

        r = client.get("/api/v1/expenses/today", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        assert len(r.json()) == 2


class TestExpensePatch:

    def test_cashier_cannot_edit_closed_shift_expense(self, client, db, cashier_user):
        shift_a = _open_shift(db, "cashiertest", "Cashier Test")
        created = client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS"},
        ).json()
        _close_shift(db, shift_a)
        _open_shift(db, "cashiertest", "Cashier Test", opening=200_000)

        r = client.patch(
            f"/api/v1/expenses/{created['id']}",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 999},
        )
        assert r.status_code == 403
        assert "closed shift" in r.json()["detail"].lower()

    def test_cashier_can_edit_current_shift_expense(self, client, db, cashier_user):
        _open_shift(db, "cashiertest", "Cashier Test")
        created = client.post(
            "/api/v1/expenses/",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 100, "category": "MEALS"},
        ).json()
        r = client.patch(
            f"/api/v1/expenses/{created['id']}",
            headers=auth_header("cashiertest", "cashier"),
            json={"amount_php": 150},
        )
        assert r.status_code == 200
        assert r.json()["amount_php"] == 150
