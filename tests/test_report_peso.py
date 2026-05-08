"""
Daily report — Peso block (treasurer drawer bookends).

Opening = first treasurer shift on the date (opening_cash_php).
Closing = last treasurer shift's closing_cash_php, falling back to
expected_cash_php while the shift is still open.
"""
from datetime import datetime, timezone, timedelta

from app.core.today import get_today
from app.models.shift import TellerShift, ShiftStatus
from tests.conftest import auth_header, _make_user

TODAY = get_today()
TODAY_ISO = TODAY.isoformat()


def _add_treasurer_shift(db, *, username, opened_at, opening_cash_php, closing_cash_php=None, expected_cash_php=None, status=ShiftStatus.OPEN):
    s = TellerShift(
        date=TODAY,
        cashier=username,
        cashier_name=username,
        status=status,
        opened_at=opened_at,
        opening_cash_php=opening_cash_php,
        closing_cash_php=closing_cash_php,
        expected_cash_php=expected_cash_php,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


class TestPesoBlock:
    def test_no_treasurer_shifts_returns_nulls(self, client, admin_user):
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        peso = r.json()["peso"]
        assert peso["opening_php"] is None
        assert peso["closing_php"] is None
        # Breakdown components present, all zero when no treasurer in DB.
        assert peso["bale_php"] == 0.0
        assert peso["vault_returns_php"] == 0.0
        assert peso["cheques_cleared_php"] == 0.0
        assert peso["expenses_php"] == 0.0

    def test_single_closed_treasurer_shift(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        now = datetime.now(timezone.utc)
        _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=4),
            opening_cash_php=2_500_000.0,
            closing_cash_php=2_750_000.0,
            expected_cash_php=2_745_000.0,
            status=ShiftStatus.CLOSED,
        )
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["opening_php"] == 2_500_000.0
        # Declared closing wins over expected when present.
        assert peso["closing_php"] == 2_750_000.0

    def test_open_treasurer_shift_falls_back_to_expected(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        now = datetime.now(timezone.utc)
        _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=2),
            opening_cash_php=1_000_000.0,
            closing_cash_php=None,
            expected_cash_php=1_120_000.0,
            status=ShiftStatus.OPEN,
        )
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["opening_php"] == 1_000_000.0
        assert peso["closing_php"] == 1_120_000.0

    def test_multiple_treasurer_shifts_use_first_and_last(self, client, admin_user, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        _make_user(db, "treas2", "supervisor", "Treasurer 2")
        now = datetime.now(timezone.utc)
        _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=8),
            opening_cash_php=2_000_000.0,
            closing_cash_php=2_100_000.0,
            status=ShiftStatus.CLOSED,
        )
        _add_treasurer_shift(
            db, username="treas2",
            opened_at=now - timedelta(hours=2),
            opening_cash_php=2_100_000.0,
            closing_cash_php=2_400_000.0,
            status=ShiftStatus.CLOSED,
        )
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        # Earliest opening, latest closing.
        assert peso["opening_php"] == 2_000_000.0
        assert peso["closing_php"] == 2_400_000.0

    def test_breakdown_aggregates_bale_and_expenses(self, client, admin_user, db):
        from app.models.shift import CashReplenishment
        from app.models.expense import Expense, ExpenseStatus
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        now = datetime.now(timezone.utc)
        shift = _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=4),
            opening_cash_php=1_000_000.0,
            closing_cash_php=1_200_000.0,
            status=ShiftStatus.CLOSED,
        )
        # Bale (vault → drawer) on this treasurer shift.
        db.add(CashReplenishment(shift_id=shift.id, amount_php=300_000.0, source="SAFE"))
        # Treasurer-bucket expense (no shift_id).
        db.add(Expense(
            date=TODAY, amount_php=4_500.0, category="OFFICE_SUPPLIES",
            description="paper", recorded_by="treas1", shift_id=None,
            status=ExpenseStatus.APPROVED,
        ))
        # Rejected expense should NOT count.
        db.add(Expense(
            date=TODAY, amount_php=10_000.0, category="OFFICE_SUPPLIES",
            description="reversed", recorded_by="treas1", shift_id=None,
            status=ExpenseStatus.REJECTED,
        ))
        db.commit()

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["bale_php"] == 300_000.0
        assert peso["expenses_php"] == 4_500.0
        assert peso["vault_returns_php"] == 0.0
        assert peso["cheques_cleared_php"] == 0.0

    def test_cashier_shift_does_not_count(self, client, admin_user, db):
        _make_user(db, "casher1", "cashier", "Cashier 1")
        now = datetime.now(timezone.utc)
        _add_treasurer_shift(
            db, username="casher1",  # cashier role, not supervisor
            opened_at=now - timedelta(hours=3),
            opening_cash_php=999_999.0,
            closing_cash_php=999_999.0,
            status=ShiftStatus.CLOSED,
        )
        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["opening_php"] is None
        assert peso["closing_php"] is None
