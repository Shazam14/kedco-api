"""
Cash Map — where every peso physically lives, right now.

Replaces the dashboard's stale `php_cash` rollup. Sums 5 buckets:
  1. Cashier drawer  — open cashier + treasurer shifts (live expected)
  2. Cashier handoff — closed cashier shifts not yet absorbed by an
                       open treasurer's window
  3. Rider in-field  — IN_FIELD dispatches: cash_php (cumulative incl. topups)
                       + rider-side received SELLs − received BUYs
  4. Rider remitted  — REMITTED (not yet RETURNED) dispatch.remit_php
  5. Vault           — running net of safe_movements

30s in-memory TTL cache, same pattern as dashboard.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

from app.core.database import get_db
from app.core.today import get_today
from app.models.shift import TellerShift, ShiftStatus, SafeMovement
from app.models.transaction import (
    Transaction, TxnType, RiderDispatch, DispatchStatus, PaymentStatus,
)
from app.models.expense import Expense, ExpenseStatus
from app.models.user import User, UserRole
from app.api.v1.auth import require_role, TokenData
from app.api.v1.shifts import _treasurer_aggregates, _comm
from app.services.shifts import compute_expected_cash, compute_expected_cash_treasurer
from app.services.payments import received_php as _slice_received, received_share as _received_share

router = APIRouter(prefix="/cash-map", tags=["cash-map"])

_cache: dict = {}
_CACHE_TTL = 30  # seconds


def _open_shift_expected(shift: TellerShift, db: Session, is_treasurer: bool) -> float:
    """Live rolling drawer cash for an OPEN shift."""
    if is_treasurer:
        agg = _treasurer_aggregates(shift, db)
        if agg is None:
            return shift.opening_cash_php
        return compute_expected_cash_treasurer(
            opening_cash=shift.opening_cash_php,
            from_dispatches=agg["from_dispatches_php"],
            dispatches_out=agg["dispatches_out_php"],
            from_cashier=agg["from_cashier_php"],
            bale_peso=agg["bale_peso_php"],
            inter_branch_in=agg["inter_branch_in_php"],
            inter_branch_out=agg["inter_branch_out_php"],
            vault_returns=agg["vault_returns_php"],
            expenses=agg["expenses_php"],
            cheques_cleared=agg["cheques_cleared_php"],
            peso_ken_in=agg["peso_ken_in_php"],
            peso_ken_out=agg["peso_ken_out_php"],
            vale_in=agg["vale_in_php"],
            vale_out=agg["vale_out_php"],
            cashier_floats_out=agg["cashier_floats_out_php"],
            counter_sells_net=agg["counter_sells_net_php"],
        )
    # Cashier shift
    txns = db.query(Transaction).filter_by(
        date=shift.date, cashier=shift.cashier,
    ).all()
    sold = sum(_slice_received(t) for t in txns if t.type == TxnType.SELL)
    bought = sum(_slice_received(t) for t in txns if t.type == TxnType.BUY)
    comm = sum(_comm(t) * _received_share(t) for t in txns)
    replen = sum(r.amount_php for r in shift.replenishments)
    petty_rows = db.query(Expense).filter(
        Expense.shift_id == shift.id,
        Expense.status != ExpenseStatus.REJECTED,
    ).all()
    petty = sum(e.amount_php for e in petty_rows)
    return compute_expected_cash(
        shift.opening_cash_php, sold, bought, comm, replen, petty,
    )


@router.get("")
async def get_cash_map(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    cache_key = f"cash-map:{today}"
    entry = _cache.get(cache_key)
    if entry and (datetime.utcnow() - entry["ts"]).total_seconds() < _CACHE_TTL:
        return entry["data"]

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()

    shifts_today = (
        db.query(TellerShift)
        .filter(TellerShift.date == today)
        .filter(~TellerShift.cashier.in_(demo_users))
        .all()
    )
    user_lookup = {u.username: u for u in db.query(User).all()}

    open_treasurer_present = any(
        s.status == ShiftStatus.OPEN
        and user_lookup.get(s.cashier)
        and user_lookup[s.cashier].role == UserRole.supervisor
        for s in shifts_today
    )

    rows = []
    drawer_total = 0.0
    handoff_total = 0.0

    for shift in shifts_today:
        owner = user_lookup.get(shift.cashier)
        is_treasurer = bool(owner and owner.role == UserRole.supervisor)

        if shift.status == ShiftStatus.OPEN:
            amount = _open_shift_expected(shift, db, is_treasurer)
            drawer_total += amount
            rows.append({
                "location": "Treasurer Drawer" if is_treasurer else "Cashier Drawer",
                "holder": shift.cashier_name,
                "amount": round(amount, 2),
                "status": "OPEN",
                "since": shift.opened_at.isoformat() if shift.opened_at else None,
                "terminal_id": shift.terminal_id,
                "branch_id": shift.branch_id,
            })
        elif (
            shift.status == ShiftStatus.CLOSED
            and not is_treasurer
            and shift.closing_cash_php is not None
            and not open_treasurer_present
        ):
            # Cash sits in handoff state — treasurer hasn't received it yet
            # (or no treasurer is on duty to absorb it).
            handoff_total += shift.closing_cash_php
            rows.append({
                "location": "Cashier Handoff",
                "holder": shift.cashier_name,
                "amount": round(shift.closing_cash_php, 2),
                "status": "CLOSED",
                "since": shift.closed_at.isoformat() if shift.closed_at else None,
                "terminal_id": shift.terminal_id,
                "branch_id": shift.branch_id,
            })

    # Rider buckets
    in_field_total = 0.0
    remitted_total = 0.0
    dispatches = (
        db.query(RiderDispatch)
        .filter(RiderDispatch.date == today)
        .filter(RiderDispatch.status.in_([DispatchStatus.IN_FIELD, DispatchStatus.REMITTED]))
        .all()
    )
    for d in dispatches:
        if d.status == DispatchStatus.IN_FIELD:
            txns = db.query(Transaction).filter_by(dispatch_id=d.id).all()
            sold = sum(_slice_received(t) for t in txns if t.type == TxnType.SELL)
            bought = sum(_slice_received(t) for t in txns if t.type == TxnType.BUY)
            amount = (d.cash_php or 0) + sold - bought
            in_field_total += amount
            rows.append({
                "location": "Rider Field",
                "holder": d.rider_name,
                "amount": round(amount, 2),
                "status": "IN_FIELD",
                "since": d.created_at.isoformat() if d.created_at else None,
            })
        else:  # REMITTED
            amount = d.remit_php or 0
            remitted_total += amount
            rows.append({
                "location": "Rider Remit",
                "holder": d.rider_name,
                "amount": round(amount, 2),
                "status": "REMITTED",
                "since": d.updated_at.isoformat() if d.updated_at else None,
            })

    # Vault — running net of every safe_movement ever recorded
    vault_total = db.query(
        func.coalesce(func.sum(SafeMovement.amount_php), 0.0)
    ).scalar() or 0.0
    vault_total = float(vault_total)
    last_movement = (
        db.query(SafeMovement)
        .order_by(SafeMovement.created_at.desc())
        .first()
    )
    rows.append({
        "location": "Vault",
        "holder": "—",
        "amount": round(vault_total, 2),
        "status": "—",
        "since": last_movement.created_at.isoformat() if last_movement and last_movement.created_at else None,
    })

    total = drawer_total + handoff_total + in_field_total + remitted_total + vault_total

    data = {
        "date": str(today),
        "rollup": {
            "cashiers": {
                "drawer": round(drawer_total, 2),
                "handoff": round(handoff_total, 2),
            },
            "riders": {
                "in_field": round(in_field_total, 2),
                "remitted_unconfirmed": round(remitted_total, 2),
            },
            "vault": round(vault_total, 2),
            "total": round(total, 2),
        },
        "rows": rows,
        "expected": None,    # v1: variance check parked — needs cross-day reconciliation
        "variance": None,
    }

    _cache[cache_key] = {"ts": datetime.utcnow(), "data": data}
    return data
