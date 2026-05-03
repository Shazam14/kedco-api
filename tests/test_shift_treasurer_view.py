"""Treasurer-side aggregates on the shift summary.

Cashier shifts must see `is_treasurer_shift=False` and the new fields stay None
(no behavior change). Supervisor shifts get overall totals + dispatches/handoffs/bale.
"""
import uuid
from datetime import datetime, time, timedelta

from app.core.today import get_today
from app.models.shift import TellerShift, ShiftStatus, CashReplenishment, SafeMovement
from app.models.transaction import RiderDispatch, DispatchStatus
from tests.conftest import auth_header


def _open_shift(db, *, cashier: str, opening: float = 100_000.0, opened_at=None) -> TellerShift:
    s = TellerShift(
        id=uuid.uuid4(),
        date=get_today(),
        cashier=cashier,
        cashier_name=cashier,
        status=ShiftStatus.OPEN,
        opening_cash_php=opening,
        opened_at=opened_at or datetime.now() - timedelta(hours=1),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _close_shift(db, shift: TellerShift, closing: float, closed_at=None) -> TellerShift:
    shift.status = ShiftStatus.CLOSED
    shift.closing_cash_php = closing
    shift.closed_at = closed_at or datetime.now()
    db.commit()
    db.refresh(shift)
    return shift


def test_cashier_shift_has_no_treasurer_fields(client, db, cashier_user):
    _open_shift(db, cashier=cashier_user.username)
    res = client.get("/api/v1/shifts/active", headers=auth_header(cashier_user.username, "cashier"))
    assert res.status_code == 200
    body = res.json()
    assert body["is_treasurer_shift"] is False
    assert body["overall_total_bought_php"] is None
    assert body["from_dispatches_php"] is None
    assert body["bale_peso_php"] is None


def test_treasurer_shift_flips_treasurer_flag(client, db, supervisor_user):
    _open_shift(db, cashier=supervisor_user.username)
    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 200
    body = res.json()
    assert body["is_treasurer_shift"] is True
    assert body["overall_total_bought_php"] == 0
    assert body["from_dispatches_php"] == 0
    assert body["dispatches_out_php"] == 0
    assert body["from_cashier_php"] == 0
    assert body["bale_peso_php"] == 0
    assert body["vault_returns_php"] == 0


def test_overall_totals_sum_all_cashier_txns(client, db, supervisor_user, cashier_user, make_transaction):
    _open_shift(db, cashier=supervisor_user.username)
    make_transaction(type="SELL", php_amt=50_000, cashier=cashier_user.username)
    make_transaction(type="BUY",  php_amt=30_000, cashier=cashier_user.username)
    # PENDING txn excluded
    make_transaction(type="SELL", php_amt=99_999, cashier=cashier_user.username, payment_status="PENDING")

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["overall_total_sold_php"]   == 50_000
    assert body["overall_total_bought_php"] == 30_000


def test_from_dispatches_sums_only_in_window_remits(client, db, supervisor_user, make_dispatch):
    # Anchor wall-clock timestamps to the operational date so override is OFF
    # and the wall-clock window filter is what's exercised here.
    op_today = get_today()
    shift_open = datetime.combine(op_today, time(10, 0))
    _open_shift(db, cashier=supervisor_user.username, opened_at=shift_open)

    # In-window REMITTED dispatch counts.
    d1 = make_dispatch(cash_php=100_000)
    d1.remit_php = 80_000
    d1.status = DispatchStatus.REMITTED
    d1.updated_at = datetime.combine(op_today, time(11, 0))
    db.commit()

    # Pre-window dispatch (closed BEFORE shift opened) — should NOT count.
    d2 = make_dispatch(cash_php=200_000)
    d2.remit_php = 150_000
    d2.status = DispatchStatus.RETURNED
    d2.updated_at = shift_open - timedelta(hours=1)
    db.commit()

    # Still IN_FIELD — not remitted, doesn't count.
    make_dispatch(cash_php=50_000)

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["from_dispatches_php"] == 80_000


def test_dispatches_out_counts_only_own_dispatches(client, db, supervisor_user, rider_user):
    """Treasurer's expected drawer subtracts cash she dispatched. Dispatches by
    other treasurers (different `dispatched_by`) belong to their drawer math."""
    _open_shift(db, cashier=supervisor_user.username)

    def _add_dispatch(amount: float, by: str) -> None:
        db.add(RiderDispatch(
            id=uuid.uuid4(),
            date=get_today(),
            rider_username=rider_user.username,
            rider_name=rider_user.full_name,
            status=DispatchStatus.IN_FIELD,
            dispatch_time="09:00 AM",
            cash_php=amount,
            dispatched_by=by,
        ))
        db.commit()

    # Two dispatches by this treasurer — count.
    _add_dispatch(300_000, supervisor_user.username)
    _add_dispatch(150_000, supervisor_user.username)
    # One dispatched by someone else — doesn't count toward her drawer.
    _add_dispatch(999_999, "some_other_treasurer")

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["dispatches_out_php"] == 450_000


def test_from_cashier_excludes_same_terminal_handoffs(client, db, supervisor_user, cashier_user):
    """When cashier1 closes and cashier2 opens on the same terminal, cashier1's
    closing was a handoff — not a return to treasurer. Only the LAST shift per
    terminal counts."""
    shift_open = datetime.now() - timedelta(hours=4)
    _open_shift(db, cashier=supervisor_user.username, opened_at=shift_open)

    # cashier1: opened first, closed early on Counter 1 → handed off to cashier2
    cs1 = _open_shift(db, cashier=cashier_user.username, opening=10_000,
                      opened_at=shift_open + timedelta(minutes=5))
    cs1.terminal_id = "Counter 1"
    db.commit()
    _close_shift(db, cs1, closing=292_832,
                 closed_at=shift_open + timedelta(hours=1))

    # cashier2: opened on same terminal AFTER cashier1 closed (the handoff)
    cs2 = _open_shift(db, cashier="cashier2", opening=292_832,
                      opened_at=shift_open + timedelta(hours=1, minutes=1))
    cs2.terminal_id = "Counter 1"
    db.commit()
    _close_shift(db, cs2, closing=37_748,
                 closed_at=datetime.now() - timedelta(minutes=10))

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    # Only cashier2's 37,748 returned to treasurer; cs1's 292,832 was a handoff.
    assert body["from_cashier_php"] == 37_748


def test_from_cashier_sums_other_cashier_closes_in_window(client, db, supervisor_user, cashier_user):
    shift_open = datetime.now() - timedelta(hours=2)
    treasurer_shift = _open_shift(db, cashier=supervisor_user.username, opened_at=shift_open)

    # Cashier closed during the treasurer's window — counts.
    cs1 = _open_shift(db, cashier=cashier_user.username, opening=10_000)
    _close_shift(db, cs1, closing=75_000, closed_at=datetime.now() - timedelta(minutes=15))

    # Cashier closed BEFORE the treasurer opened — doesn't count.
    cs2 = _open_shift(db, cashier="cashier2", opening=5_000, opened_at=shift_open - timedelta(hours=3))
    _close_shift(db, cs2, closing=88_888, closed_at=shift_open - timedelta(hours=2))

    # Treasurer's own shift wouldn't count either even if closed (id != filter).
    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["from_cashier_php"] == 75_000


def test_bale_peso_only_safe_sourced_replenishments(client, db, supervisor_user):
    shift = _open_shift(db, cashier=supervisor_user.username)
    db.add_all([
        CashReplenishment(id=uuid.uuid4(), shift_id=shift.id, amount_php=500_000, source="SAFE"),
        CashReplenishment(id=uuid.uuid4(), shift_id=shift.id, amount_php=20_000,  source="EXTERNAL"),
        CashReplenishment(id=uuid.uuid4(), shift_id=shift.id, amount_php=10_000,  source="OTHER"),
    ])
    db.commit()

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["bale_peso_php"] == 500_000
    # All replenishments still counted in total_replenishment_php (unchanged).
    assert body["total_replenishment_php"] == 530_000


def test_window_under_date_override_uses_operational_date(client, db, supervisor_user, make_dispatch):
    """Date override: shift opened on a physical day after its operational date.
    Movements timestamped (wall-clock) before opened_at but on the operational
    date must still be counted — wall-clock window scoping would drop them."""
    operational_date = get_today()
    physical_open = datetime.now() + timedelta(days=8)  # simulates override: opened "later" in real time
    _open_shift(db, cashier=supervisor_user.username, opened_at=physical_open)

    # Vault deposit made on the operational date with a wall-clock created_at
    # that predates physical_open by ~8 days.
    db.add(SafeMovement(
        id=uuid.uuid4(),
        amount_php=1_000_000,
        reason="MANUAL_DEPOSIT",
        actor_username=supervisor_user.username,
        movement_date=operational_date,
        created_at=datetime.now() - timedelta(hours=1),
    ))

    # Rider remit on the same operational date, also pre-physical_open.
    d = make_dispatch(cash_php=200_000)
    d.remit_php = 150_000
    d.status = DispatchStatus.REMITTED
    d.updated_at = datetime.now() - timedelta(hours=1)
    db.commit()

    res = client.get("/api/v1/shifts/active", headers=auth_header(supervisor_user.username, "supervisor"))
    body = res.json()
    assert body["vault_returns_php"]   == 1_000_000
    assert body["from_dispatches_php"] == 150_000


def test_treasurer_close_uses_treasurer_formula(client, db, supervisor_user, cashier_user, make_dispatch):
    shift_open = datetime.now() - timedelta(hours=2)
    _open_shift(db, cashier=supervisor_user.username, opening=100_000, opened_at=shift_open)

    # +50k from a rider remit
    d1 = make_dispatch(cash_php=80_000)
    d1.remit_php = 50_000
    d1.status = DispatchStatus.REMITTED
    d1.updated_at = datetime.now() - timedelta(minutes=30)
    db.commit()

    # +75k from a cashier handoff
    cs1 = _open_shift(db, cashier=cashier_user.username, opening=10_000)
    _close_shift(db, cs1, closing=75_000)

    # 200k bale peso pulled from vault
    treasurer_shift_id = (
        db.query(TellerShift)
        .filter_by(cashier=supervisor_user.username, status=ShiftStatus.OPEN)
        .first()
        .id
    )
    db.add(CashReplenishment(id=uuid.uuid4(), shift_id=treasurer_shift_id, amount_php=200_000, source="SAFE"))
    db.commit()

    # Expected (treasurer formula) = 100k + 50k + 75k − 200k bale = 25k.
    # Bale is a vault liability; treasurer keeps it segregated from her own-money tally.
    res = client.post(
        "/api/v1/shifts/close",
        headers=auth_header(supervisor_user.username, "supervisor"),
        json={"closing_cash_php": 25_000},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expected_cash_php"] == 25_000
    assert body["cash_variance"]     == 0
