from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date

from app.core.database import get_db
from app.models.shift import TellerShift, ShiftStatus, CashReplenishment, SafeMovement, InterBranchOutflow, TreasurerFloat
from app.models.transaction import Transaction, TxnPayment, PaymentMode, PaymentStatus, RiderDispatch, DispatchStatus
from app.models.expense import Expense, ExpenseStatus
from app.models.user import User, UserRole
from app.models.capital import PesoKenEntry, ValeParty, ValeEntry
from app.models.audit import AuditLog
from app.schemas.shift import ShiftOpenIn, ShiftCloseIn, ReplenishIn, ShiftOut, ReplenishmentOut, InterBranchOutIn, InterBranchOutflowOut, PesoKenOutIn, ValeOutIn, ReconciliationPatchIn
from app.api.v1.auth import require_role, TokenData
import uuid
from app.core.today import get_today
from app.services.shifts import compute_expected_cash, compute_variance, compute_expected_cash_treasurer
from app.services.payments import received_php as _slice_received, received_share as _received_share

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

    overall_txns = (
        db.query(Transaction)
        .filter(Transaction.date == shift.date)
        .filter(~Transaction.cashier.in_(demo_users))
        .all()
    )
    overall_bought = sum(_slice_received(t) for t in overall_txns if t.type == "BUY")
    overall_sold   = sum(_slice_received(t) for t in overall_txns if t.type == "SELL")

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
    # Cash received from another branch (drawer-positive, vault not involved).
    inter_branch_in = sum(r.amount_php for r in shift.replenishments if r.source == "INTER_BRANCH")
    # Cash pulled from Ken's personal float into the drawer (positive).
    peso_ken_in = sum(r.amount_php for r in shift.replenishments if r.source == "PESO_KEN")
    # Cash from external party (vale/IOU, typically investor) into the drawer.
    vale_in = sum(r.amount_php for r in shift.replenishments if r.source == "VALE")
    # Drawer outflows split by destination (BRANCH vs PESO_KEN vs VALE).
    inter_branch_out = sum(o.amount_php for o in shift.inter_branch_outflows if (o.destination or "BRANCH") == "BRANCH")
    peso_ken_out = sum(o.amount_php for o in shift.inter_branch_outflows if o.destination == "PESO_KEN")
    vale_out = sum(o.amount_php for o in shift.inter_branch_outflows if o.destination == "VALE")

    # Signed net of vault movements by this treasurer during her shift window.
    # + = drawer→vault deposit, − = vault→drawer withdrawal. Formula subtracts
    # this so withdrawals add to expected drawer cash, deposits subtract.
    vault_movements_q = (
        db.query(SafeMovement)
        .filter(SafeMovement.movement_date == shift.date)
        .filter(SafeMovement.actor_username == shift.cashier)
        .filter(SafeMovement.created_at <= window_end)
    )
    if window_start is not None:
        vault_movements_q = vault_movements_q.filter(SafeMovement.created_at >= window_start)
    vault_movements = vault_movements_q.all()
    vault_returns = sum(m.amount_php for m in vault_movements)

    # Treasurer-bucket expenses: rows recorded by this treasurer on this date.
    # Once treasurers got TellerShifts, their expenses carry shift_id (their own
    # treasurer shift) — recorded_by is the only stable signal that an expense
    # belongs to this treasurer's drawer. Cashier petty cash has cashier
    # username so it can never leak in.
    expenses_rows = (
        db.query(Expense)
        .filter(Expense.date == shift.date)
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

    # Cashier opening floats handed out by THIS treasurer on this date.
    # Each row's amount is the latest assignment (overwrites in place), so
    # summing gives the cash that physically left her drawer to cashiers.
    cashier_floats_out = sum(
        f.amount_php for f in db.query(TreasurerFloat)
        .filter(TreasurerFloat.date == shift.date)
        .filter(TreasurerFloat.treasurer_username == shift.cashier)
        .all()
    )

    # Treasurer-direct counter txns: when the treasurer sells/buys at her own
    # window (no rider dispatch, no separate cashier shift), the PHP moves
    # straight in/out of her drawer. PENDING excluded — no cash yet.
    counter_txns = (
        db.query(Transaction)
        .filter(Transaction.date == shift.date)
        .filter(Transaction.cashier == shift.cashier)
        .filter(Transaction.source == "COUNTER")
        .all()
    )
    counter_sells_net = sum(
        (_slice_received(t) if t.type == "SELL" else -_slice_received(t))
        for t in counter_txns
    )

    return {
        "overall_total_bought_php": round(overall_bought, 2),
        "overall_total_sold_php":   round(overall_sold, 2),
        "from_dispatches_php":      round(from_dispatches, 2),
        "dispatches_out_php":       round(dispatches_out, 2),
        "from_cashier_php":         round(from_cashier, 2),
        "bale_peso_php":            round(bale_peso, 2),
        "inter_branch_in_php":      round(inter_branch_in, 2),
        "inter_branch_out_php":     round(inter_branch_out, 2),
        "peso_ken_in_php":          round(peso_ken_in, 2),
        "peso_ken_out_php":         round(peso_ken_out, 2),
        "vale_in_php":              round(vale_in, 2),
        "vale_out_php":             round(vale_out, 2),
        "cashier_floats_out_php":   round(cashier_floats_out, 2),
        "vault_returns_php":        round(vault_returns, 2),
        "expenses_php":             round(expenses_php, 2),
        "cheques_cleared_php":      round(cheques_cleared_php, 2),
        "counter_sells_net_php":    round(counter_sells_net, 2),
    }


def _shift_to_out(shift: TellerShift, db: Session) -> ShiftOut:
    txns = db.query(Transaction).filter_by(
        date=shift.date,
        cashier=shift.cashier,
    ).all()

    # Slice-aware: a partially-pending split contributes its received cash
    # portion to the cashier's totals (than/commission scale by share).
    total_sold       = sum(_slice_received(t) for t in txns if t.type == "SELL")
    total_bought     = sum(_slice_received(t) for t in txns if t.type == "BUY")
    total_than       = sum(t.than * _received_share(t) for t in txns)
    total_commission = sum(_comm(t) * _received_share(t) for t in txns)
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
        inter_branch_outflows=[
            InterBranchOutflowOut(
                id=str(o.id), amount_php=o.amount_php, note=o.note,
                destination=o.destination or "BRANCH", sent_at=o.sent_at,
            )
            for o in shift.inter_branch_outflows
        ],
        is_treasurer_shift=treasurer_view is not None,
        overall_total_bought_php=treasurer_view["overall_total_bought_php"] if treasurer_view else None,
        overall_total_sold_php=treasurer_view["overall_total_sold_php"]     if treasurer_view else None,
        from_dispatches_php=treasurer_view["from_dispatches_php"]           if treasurer_view else None,
        dispatches_out_php=treasurer_view["dispatches_out_php"]             if treasurer_view else None,
        from_cashier_php=treasurer_view["from_cashier_php"]                 if treasurer_view else None,
        bale_peso_php=treasurer_view["bale_peso_php"]                       if treasurer_view else None,
        inter_branch_in_php=treasurer_view["inter_branch_in_php"]           if treasurer_view else None,
        inter_branch_out_php=treasurer_view["inter_branch_out_php"]         if treasurer_view else None,
        vault_returns_php=treasurer_view["vault_returns_php"]               if treasurer_view else None,
        expenses_php=treasurer_view["expenses_php"]                         if treasurer_view else None,
        cheques_cleared_php=treasurer_view["cheques_cleared_php"]           if treasurer_view else None,
        peso_ken_in_php=treasurer_view["peso_ken_in_php"]                   if treasurer_view else None,
        peso_ken_out_php=treasurer_view["peso_ken_out_php"]                 if treasurer_view else None,
        vale_in_php=treasurer_view["vale_in_php"]                           if treasurer_view else None,
        vale_out_php=treasurer_view["vale_out_php"]                         if treasurer_view else None,
        cashier_floats_out_php=treasurer_view["cashier_floats_out_php"]     if treasurer_view else None,
        counter_sells_net_php=treasurer_view["counter_sells_net_php"]       if treasurer_view else None,
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
    if source not in {"TREASURER_FLOAT", "SAFE", "INTER_BRANCH", "PESO_KEN", "VALE", "EXTERNAL", "OTHER"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid source: {source}")

    vale_party = None
    if source == "VALE":
        if not body.party_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="party_id required for VALE source.")
        vale_party = db.query(ValeParty).filter_by(id=body.party_id).first()
        if not vale_party:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vale party not found.")

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
    elif source == "PESO_KEN":
        # Pulling cash from Ken's float into drawer: Ken's ledger drops by the
        # same amount so the admin Peso Ken total stays in sync.
        db.add(PesoKenEntry(
            amount_php=-abs(body.amount_php),
            note=body.note or "From Ken → drawer",
            entry_date=today,
            created_by=current_user.username,
        ))
    elif source == "VALE":
        # Cash arriving from an external party (investor IOU). Positive entry
        # = party's running balance grows (we owe them this much).
        db.add(ValeEntry(
            party_id=vale_party.id,
            amount_php=abs(body.amount_php),
            note=body.note,
            entry_date=today,
            created_by=current_user.username,
        ))

    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/inter-branch-out", response_model=ShiftOut)
async def send_inter_branch(
    body: InterBranchOutIn,
    current_user: TokenData = Depends(require_role("supervisor")),
    db: Session = Depends(get_db),
):
    """Treasurer dispatches cash from her drawer to another branch.
    Drawer-negative; vault is not touched."""
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    if body.amount_php <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be positive.")

    db.add(InterBranchOutflow(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
        destination="BRANCH",
    ))
    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/peso-ken-out", response_model=ShiftOut)
async def return_to_peso_ken(
    body: PesoKenOutIn,
    current_user: TokenData = Depends(require_role("supervisor")),
    db: Session = Depends(get_db),
):
    """Treasurer returns cash from her drawer to Ken's personal float.
    Drawer-negative; pairs with a +amount row in peso_ken_entries so Ken's
    admin ledger stays in sync."""
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    if body.amount_php <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be positive.")

    db.add(InterBranchOutflow(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
        destination="PESO_KEN",
    ))
    db.add(PesoKenEntry(
        amount_php=abs(body.amount_php),
        note=body.note or "Drawer → Ken",
        entry_date=today,
        created_by=current_user.username,
    ))
    db.commit()
    db.refresh(shift)

    return _shift_to_out(shift, db)


@router.post("/vale-out", response_model=ShiftOut)
async def return_to_vale_party(
    body: ValeOutIn,
    current_user: TokenData = Depends(require_role("supervisor")),
    db: Session = Depends(get_db),
):
    """Treasurer returns cash from her drawer to a vale party (paying back IOU).
    Drawer-negative; pairs with a −amount row in vale_entries so the party's
    running balance drops."""
    today = get_today()

    shift = db.query(TellerShift).filter_by(
        cashier=current_user.username,
        date=today,
        status=ShiftStatus.OPEN,
    ).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift found for today.")

    if body.amount_php <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be positive.")

    party = db.query(ValeParty).filter_by(id=body.party_id).first()
    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vale party not found.")

    db.add(InterBranchOutflow(
        shift_id=shift.id,
        amount_php=body.amount_php,
        note=body.note,
        destination="VALE",
    ))
    db.add(ValeEntry(
        party_id=party.id,
        amount_php=-abs(body.amount_php),
        note=body.note or f"Drawer → {party.name}",
        entry_date=today,
        created_by=current_user.username,
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
    # Slice-aware: cash portion of a split-pending txn moves cash today even
    # though the cheque/transfer leg is still in flight.
    total_sold       = sum(_slice_received(t) for t in txns if t.type == "SELL")
    total_bought     = sum(_slice_received(t) for t in txns if t.type == "BUY")
    total_commission = sum(_comm(t) * _received_share(t) for t in txns)
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
            opening_cash=shift.opening_cash_php,
            from_dispatches=treasurer_view["from_dispatches_php"],
            dispatches_out=treasurer_view["dispatches_out_php"],
            from_cashier=treasurer_view["from_cashier_php"],
            bale_peso=treasurer_view["bale_peso_php"],
            inter_branch_in=treasurer_view["inter_branch_in_php"],
            inter_branch_out=treasurer_view["inter_branch_out_php"],
            vault_returns=treasurer_view["vault_returns_php"],
            expenses=treasurer_view["expenses_php"],
            cheques_cleared=treasurer_view["cheques_cleared_php"],
            peso_ken_in=treasurer_view["peso_ken_in_php"],
            peso_ken_out=treasurer_view["peso_ken_out_php"],
            vale_in=treasurer_view["vale_in_php"],
            vale_out=treasurer_view["vale_out_php"],
            cashier_floats_out=treasurer_view["cashier_floats_out_php"],
            counter_sells_net=treasurer_view["counter_sells_net_php"],
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


_RECON_STATUSES = {"PENDING", "NOTED", "RESOLVED"}


@router.patch("/{shift_id}/reconciliation")
async def update_reconciliation(
    shift_id: str,
    payload: ReconciliationPatchIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """GAP_CHECK Phase 2 — annotate the variance on a closed shift.

    `note` is freeform. `status` defaults to NOTED when a note is present and
    no explicit status is given; otherwise honors the payload. RESOLVED is the
    sign-off state (Merly/admin has decided what the gap was, no further work).
    """
    shift = db.query(TellerShift).filter(TellerShift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    new_status = payload.status
    if new_status is None:
        new_status = "NOTED" if (payload.note or "").strip() else (shift.reconciliation_status or "PENDING")
    if new_status not in _RECON_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {sorted(_RECON_STATUSES)}")

    old = {"note": shift.reconciliation_note, "status": shift.reconciliation_status}
    shift.reconciliation_note = (payload.note or "").strip() or None
    shift.reconciliation_status = new_status
    new = {"note": shift.reconciliation_note, "status": shift.reconciliation_status}

    db.add(AuditLog(
        id=uuid.uuid4(),
        table_name="teller_shifts",
        record_id=str(shift.id),
        action="UPDATE",
        changed_by=current_user.username,
        old_value=old,
        new_value=new,
        note="reconciliation",
    ))
    db.commit()
    return {
        "id": str(shift.id),
        "reconciliation_note": shift.reconciliation_note,
        "reconciliation_status": shift.reconciliation_status,
    }
