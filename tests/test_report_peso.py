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
        # expected_cash_php was already written by a prior shift-close pass,
        # so this is a finalized projection — not flagged live.
        assert peso["closing_is_live"] is False

    def test_open_treasurer_shift_with_no_expected_projects_live(self, client, admin_user, db):
        """While treasurer's shift is OPEN and expected_cash_php hasn't been
        written yet, closing_php must come from a live projection of the
        breakdown components (so the report doesn't show ₱0.00 mid-day)."""
        from app.models.shift import CashReplenishment
        from app.models.expense import Expense, ExpenseStatus
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        now = datetime.now(timezone.utc)
        shift = _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=2),
            opening_cash_php=1_000_000.0,
            closing_cash_php=None,
            expected_cash_php=None,
            status=ShiftStatus.OPEN,
        )
        # Bale (vault → drawer) +200k
        db.add(CashReplenishment(shift_id=shift.id, amount_php=200_000.0, source="SAFE"))
        # Treasurer expense −5k
        db.add(Expense(
            date=TODAY, amount_php=5_000.0, category="OFFICE_SUPPLIES",
            description="paper", recorded_by="treas1", shift_id=None,
            status=ExpenseStatus.APPROVED,
        ))
        db.commit()

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        assert peso["opening_php"] == 1_000_000.0
        # 1,000,000 + 200,000 (bale) − 5,000 (expense) = 1,195,000
        assert peso["closing_php"] == 1_195_000.0
        assert peso["closing_is_live"] is True

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

    def test_vault_movements_signed_net(self, client, admin_user, db):
        """Vault movements net signed: deposits (+) subtract, withdrawals (−) add.
        A treasurer pulling cash from vault into her drawer should raise closing peso."""
        from app.models.shift import SafeMovement
        import uuid as _uuid
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        now = datetime.now(timezone.utc)
        _add_treasurer_shift(
            db, username="treas1",
            opened_at=now - timedelta(hours=4),
            opening_cash_php=1_000_000.0,
            closing_cash_php=None,
            expected_cash_php=None,
            status=ShiftStatus.OPEN,
        )
        # Withdrawal: vault → drawer (drawer cash UP by 500k).
        # Reason intentionally OTHER, not MANUAL_DEPOSIT — should still count.
        db.add(SafeMovement(
            id=_uuid.uuid4(),
            amount_php=-500_000.0,
            reason="OTHER",
            note="vale ike",
            actor_username="treas1",
            movement_date=TODAY,
        ))
        # Deposit: drawer → vault (drawer cash DOWN by 100k).
        db.add(SafeMovement(
            id=_uuid.uuid4(),
            amount_php=100_000.0,
            reason="MANUAL_DEPOSIT",
            actor_username="treas1",
            movement_date=TODAY,
        ))
        db.commit()

        r = client.get(f"/api/v1/report/daily?date={TODAY_ISO}", headers=auth_header("admintest", "admin"))
        peso = r.json()["peso"]
        # Net = -500k + 100k = -400k (drawer received 400k net from vault).
        assert peso["vault_returns_php"] == -400_000.0
        # Closing = opening − vault_returns = 1,000,000 − (−400,000) = 1,400,000.
        assert peso["closing_php"] == 1_400_000.0
        assert peso["closing_is_live"] is True

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
