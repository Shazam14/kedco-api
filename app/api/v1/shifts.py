from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date

from app.core.database import get_db
from app.models.shift import TellerShift, ShiftStatus, CashReplenishment, SafeMovement
from app.models.transaction import Transaction, TxnPayment, PaymentMode, PaymentStatus, RiderDispatch, DispatchStatus
from app.models.expense import Expense, ExpenseStatus
from app.models.user import User, UserRole
from app.schemas.shift import ShiftOpenIn, ShiftCloseIn, ReplenishIn, ShiftOut, ReplenishmentOut
from app.api.v1.auth import require_role, TokenData
from app.core.today import get_today
from app.services.shifts import compute_expected_cash, compute_variance, compute_expected_cash_treasurer

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _comm(t):
    if not t.official_rate:
        return 0.0
    return (t.rate - t.official_rate) * t.foreign_amt if str(t.type) == "SELL" \
        else (t.official_rate - t.rate) * t.foreign_amt


def _treasurer_aggregates(shift: TellerShift, db: Session) -> dict | None:
    """Return treasurer-side roll-ups when this shift is owned by a supervisor.
    Cashier shifts return None — keeps the cashier ShiftOut payload unchanged.
    """
    owner = db.query(User).filter_by(username=shift.cashier).first()
    if not owner or owner.role != UserRole.supervisor:
        return None

    window_end = shift.closed_at or datetime.now()

    # When the date override is active, `shift.date` (operational) and
    # `shift.opened_at.date()` (physical wall-clock) diverge — operational
    # entries can have wall-clock timestamps that predate the shift's physical
    # opened_at. In that case, drop the wall-clock lower bound and scope by
    # operational date alone. Otherwise, preserve normal multi-shift scoping.
    override_active = shift.date != shift.opened_at.date()
    window_start = None if override_active else shift.opened_at

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()

    received = lambda t: t.payment_status != PaymentStatus.PENDING

    overall_txns = (
        db.query(Transaction)
        .filter(Transaction.date == shift.date)
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )
    overall_bought = sum(t.php_amt for t in overall_txns if t.type == "BUY"  and received(t))
    overall_sold   = sum(t.php_amt for t in overall_txns if t.type == "SELL" and received(t))

    # Rider returns physically reaching the treasurer's drawer during her window.
    # `from_dispatches` = remits in (positive cash flow into drawer).
    # `dispatches_out` = cash she handed out at dispatch time (negative flow).
    # Net dispatch impact = from_dispatches − dispatches_out.
    dispatches_q = (
        db.query(RiderDispatch)
        .filter(RiderDispatch.date == shift.date)
        .filter(RiderDispatch.status.in_([DispatchStatus.REMITTED, DispatchStatus.RETURNED]))
        .filter(RiderDispatch.updated_at <= window_end)
    )
    if window_start is not None:
        dispatches_q = dispatches_q.filter(RiderDispatch.updated_at >= window_start)
    dispatches = dispatches_q.all()
    from_dispatches = sum(d.remit_php or 0 for d in dispatches)

    # Cash she dispatched (cash_php is cumulative, includes any topups).
    # Filter to dispatches initiated by this treasurer — others' dispatches
    # already affected a previous treasurer's drawer.
    own_dispatches = (
        db.query(RiderDispatch)
        .filter(RiderDispatch.date == shift.date)
        .filter(RiderDispatch.dispatched_by == shift.cashier)
        .all()
    )
    dispatches_out = sum(d.cash_php or 0 for d in own_dispatches)

    # Cashier shifts whose closing cash physically reached the treasurer.
    # A shift that handed off to a later shift on the same terminal didn't —
    # only count the LAST shift per terminal (no later shift on that terminal).
    candidate_closes_q = (
        db.query(TellerShift)
        .filter(TellerShift.date == shift.date)
        .filter(TellerShift.id != shift.id)
        .filter(TellerShift.status == ShiftStatus.CLOSED)
        .filter(TellerShift.closed_at <= window_end)
    )
    if window_start is not None:
        candidate_closes_q = candidate_closes_q.filter(TellerShift.closed_at >= window_start)
    candidate_closes = candidate_closes_q.all()
    cashier_closes = []
    for cs in candidate_closes:
        later_on_same_terminal = (
            db.query(TellerShift)
            .filter(TellerShift.id != cs.id)
            .filter(TellerShift.id != shift.id)
            .filter(TellerShift.date == cs.date)
            .filter(TellerShift.terminal_id == cs.terminal_id)
            .filter(TellerShift.opened_at > cs.opened_at)
            .first()
        )
        if later_on_same_terminal is None:
            cashier_closes.append(cs)
    from_cashier = sum(s.closing_cash_php or 0 for s in cashier_closes)

    bale_peso = sum(r.amount_php for r in shift.replenishments if r.source == "SAFE")

    # Drawer-to-vault deposits (manual safe deposits) made by this treasurer
    # during her shift window.
    vault_deposits_q = (
        db.query(SafeMovement)
        .filter(SafeMovement.movement_date == shift.date)
        .filter(SafeMovement.actor_username == shift.cashier)
        .filter(SafeMovement.amount_php > 0)
        .filter(SafeMovement.reason == "MANUAL_DEPOSIT")
        .filter(SafeMovement.created_at <= window_end)
    )
    if window_start is not None:
        vault_deposits_q = vault_deposits_q.filter(SafeMovement.created_at >= window_start)
    vault_deposits = vault_deposits_q.all()
    vault_returns = sum(m.amount_php for m in vault_deposits)

    # Treasurer-bucket expenses: rows on operational date with no shift_id
    # (cashier petty cash carries shift_id; treasurer's expenses don't).
    # Filter to this treasurer's recorded_by so co-treasurers' spend stays on their own drawer.
    expenses_rows = (
        db.query(Expense)
        .filter(Expense.date == shift.date)
        .filter(Expense.shift_id.is_(None))
        .filter(Expense.recorded_by == shift.cashier)
        .filter(Expense.status != ExpenseStatus.REJECTED)
        .all()
    )
    expenses_php = sum(e.amount_php for e in expenses_rows)

    # Cheques the treasurer marked cleared on this operational date. The bank
    # confirmation lands as cash on the day she clicks ✓, regardless of when
    # the cheque was originally issued. Scoped to this treasurer's clears so
    # co-treasurers don't double-count.
    # Filter on wall-clock date(cleared_at) — under date override (mock_date.txt)
    # this would mis-bucket; add an explicit `cleared_date` column if override
    # support becomes needed (post-5/1 cutover plan = no more override).
    cleared_cheques = (
        db.query(TxnPayment)
        .filter(TxnPayment.method == PaymentMode.CHEQUE)
        .filter(TxnPayment.cleared_at.isnot(None))
        .filter(func.date(TxnPayment.cleared_at) == shift.date)
        .filter(TxnPayment.cleared_by == shift.cashier)
        .all()
    )
    cheques_cleared_php = sum(p.amount_php for p in cleared_cheques)

    return {
        "overall_total_bought_php": round(overall_bought, 2),
        "overall_total_sold_php":   round(overall_sold, 2),
        "from_dispatches_php":      round(from_dispatches, 2),
        "dispatches_out_php":       round(dispatches_out, 2),
        "from_cashier_php":         round(from_cashier, 2),
        "bale_peso_php":            round(bale_peso, 2),
        "vault_returns_php":        round(vault_returns, 2),
        "expenses_php":             round(expenses_php, 2),
        "cheques_cleared_php":      round(cheques_cleared_php, 2),
    }


def _shift_to_out(shift: TellerShift, db: Session) -> ShiftOut:
    txns = db.query(Transaction).filter_by(
        date=shift.date,
        cashier=shift.cashier,
    ).all()

    # PENDING transactions excluded from financial totals — cashier hasn't
    # received the PHP yet on a PENDING SELL, hasn't paid yet on a PENDING BUY.
    received = lambda t: t.payment_status != PaymentStatus.PENDING
    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL" and received(t))
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY"  and received(t))
    total_than       = sum(t.than for t in txns if received(t))
    total_commission = sum(_comm(t) for t in txns if received(t))
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

    # PENDING + APPROVED count against the till (cash already left); REJECTED
    # means admin reversed it, so the cashier's drawer should reconcile as if
    # the expense never happened.
    petty_cash_rows = db.query(Expense).filter(
        Expense.shift_id == shift.id,
        Expense.status != ExpenseStatus.REJECTED,
    ).all()
    total_petty_cash = sum(e.amount_php for e in petty_cash_rows)

    treasurer_view = _treasurer_aggregates(shift, db)

    return ShiftOut(
        id=str(shift.id),
        date=shift.date,
        cashier=shift.cashier,
        cashier_name=shift.cashier_name,
        status=shift.status.value,
        opened_at=shift.opened_at,
        closed_at=shift.closed_at,
        opening_cash_php=shift.opening_cash_php,
        closing_cash_php=shift.closing_cash_php,
        expected_cash_php=shift.expected_cash_php,
        cash_variance=shift.cash_variance,
        notes=shift.notes,
        terminal_id=shift.terminal_id,
        branch_id=shift.branch_id,
        txn_count=len(txns),
        total_sold_php=round(total_sold, 2),
        total_bought_php=round(total_bought, 2),
        total_than=round(total_than, 2),
        total_commission=round(total_commission, 2),
        total_replenishment_php=round(total_replenishment, 2),
        total_petty_cash_php=round(total_petty_cash, 2),
        replenishments=[
            ReplenishmentOut(id=str(r.id), amount_php=r.amount_php, note=r.note, source=r.source, added_at=r.added_at)
            for r in shift.replenishments
        ],
        is_treasurer_shift=treasurer_view is not None,
        overall_total_bought_php=treasurer_view["overall_total_bought_php"] if treasurer_view else None,
        overall_total_sold_php=treasurer_view["overall_total_sold_php"]     if treasurer_view else None,
        from_dispatches_php=treasurer_view["from_dispatches_php"]           if treasurer_view else None,
        dispatches_out_php=treasurer_view["dispatches_out_php"]             if treasurer_view else None,
        from_cashier_php=treasurer_view["from_cashier_php"]                 if treasurer_view else None,
        bale_peso_php=treasurer_view["bale_peso_php"]                       if treasurer_view else None,
        vault_returns_php=treasurer_view["vault_returns_php"]               if treasurer_view else None,
        expenses_php=treasurer_view["expenses_php"]                         if treasurer_view else None,
        cheques_cleared_php=treasurer_view["cheques_cleared_php"]           if treasurer_view else None,
    )


@router.post("/open", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(
    body: ShiftOpenIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    existing = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open shift today. Close it before opening a new one.",
        )

    user = db.query(User).filter_by(username=current_user.username).first()
    cashier_name = user.full_name if user else current_user.username

    shift = TellerShift(
        date=today,
        cashier=current_user.username,
        cashier_name=cashier_name,
        status=ShiftStatus.OPEN,
        opening_cash_php=body.opening_cash_php,
        notes=body.notes,
        terminal_id=body.terminal_id or None,
        branch_id=body.branch_id or None,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/replenish", response_model=ShiftOut)
async def replenish_cash(
    body: ReplenishIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    source = (body.source or "TREASURER_FLOAT").upper()
    if source not in {"TREASURER_FLOAT", "SAFE", "EXTERNAL", "OTHER"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid source: {source}")

    replenishment = CashReplenishment(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
        source=source,
    )
    db.add(replenishment)
    db.flush()  # need replenishment.id for the paired safe movement

    if source == "SAFE":
        db.add(SafeMovement(
            amount_php=-abs(body.amount_php),
            reason="REPLENISH_DRAWER",
            note=body.note,
            actor_username=current_user.username,
            related_replenishment_id=replenishment.id,
            movement_date=today,
        ))

    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/close", response_model=ShiftOut)
async def close_shift(
    body: ShiftCloseIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    txns = db.query(Transaction).filter_by(
        date=today,
        cashier=current_user.username,
    ).all()
    # PENDING transactions don't move cash on the cashier side until confirmed.
    received = lambda t: t.payment_status != PaymentStatus.PENDING
    total_sold       = sum(t.php_amt for t in txns if t.type == "SELL" and received(t))
    total_bought     = sum(t.php_amt for t in txns if t.type == "BUY"  and received(t))
    total_commission = sum(_comm(t) for t in txns if received(t))
    total_replenishment = sum(r.amount_php for r in shift.replenishments)

    # Petty cash logged during this specific shift.
    # PENDING + APPROVED count; REJECTED means admin reversed the expense.
    petty_cash_rows = db.query(Expense).filter(
        Expense.shift_id == shift.id,
        Expense.status != ExpenseStatus.REJECTED,
    ).all()
    total_petty_cash = sum(e.amount_php for e in petty_cash_rows)

    treasurer_view = _treasurer_aggregates(shift, db)
    if treasurer_view is not None:
        expected = compute_expected_cash_treasurer(
            shift.opening_cash_php,
            treasurer_view["from_dispatches_php"],
            treasurer_view["dispatches_out_php"],
            treasurer_view["from_cashier_php"],
            treasurer_view["bale_peso_php"],
            treasurer_view["vault_returns_php"],
            treasurer_view["expenses_php"],
            treasurer_view["cheques_cleared_php"],
        )
        variance = compute_variance(body.closing_cash_php, expected)
    else:
        expected = compute_expected_cash(
            shift.opening_cash_php,
            total_sold, total_bought, total_commission, total_replenishment,
            total_petty_cash,
        )
        variance = compute_variance(body.closing_cash_php, expected)

    shift.status            = ShiftStatus.CLOSED
    shift.closed_at         = datetime.now()
    shift.closing_cash_php  = body.closing_cash_php
    shift.expected_cash_php = expected
    shift.cash_variance     = variance
    if body.notes:
        shift.notes = body.notes

    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.get("/active", response_model=ShiftOut)
async def get_active_shift(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor")),
    db: Session = Depends(get_db),
):
    today = get_today()
    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active shift.")
    return _shift_to_out(shift, db)


@router.get("/today", response_model=list[ShiftOut])
async def get_today_shifts(
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()
    shifts = (
        db.query(TellerShift)
        .filter(TellerShift.date == get_today())
        .filter(~TellerShift.cashier.in_(demo_users))
        .order_by(TellerShift.opened_at)
        .all()
    )
    return [_shift_to_out(s, db) for s in shifts]
