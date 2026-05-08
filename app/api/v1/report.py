from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime, timedelta
from typing import Optional

from app.core.database import get_db
from app.core.today import get_today
from sqlalchemy import func
from app.models.transaction import Transaction, PaymentStatus, PaymentMode, TxnPayment, RiderDispatch, DispatchStatus
from app.models.currency import Currency, DailyPosition
from app.models.user import User, UserRole
from app.models.credit import SpecialCredit, CreditInstallment, CreditStatus
from app.models.shift import SafeMovement, TellerShift, ShiftStatus, CashReplenishment
from app.models.expense import Expense, ExpenseStatus
from app.api.v1.auth import require_role, TokenData
from app.services.shifts import compute_expected_cash_treasurer

router = APIRouter(prefix="/report", tags=["report"])


@router.get("/daily")
async def get_daily_report(
    report_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """
    Daily report: all transactions aggregated by currency and cashier.
    Replaces the 6 manual books (BUY/SELL × MAIN/2ND/OTHERS)
    plus the CASHIER and BREAKDOWN sheets.
    """
    target = report_date or get_today()

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()
    txns = (
        db.query(Transaction)
        .filter(Transaction.date == target)
        .filter(~Transaction.cashier.in_(demo_users))
        .order_by(Transaction.created_at)
        .all()
    )

    currencies = {c.code: c for c in db.query(Currency).all()}

    # ── Per-slice helpers ────────────────────────────────────────────────
    # Phase 4: PENDING is per-slice. A SELL with CASH-RECEIVED + GCASH-PENDING
    # is half-pending, not all-pending. Pre-split fallback: parent.payment_status
    # is authoritative if no slices exist (defensive — Phase 1 backfilled all).
    def _slice_pending_php(t):
        if t.payments:
            return sum(p.amount_php for p in t.payments if p.status == PaymentStatus.PENDING)
        return t.php_amt if t.payment_status == PaymentStatus.PENDING else 0.0

    def _slice_received_php(t):
        if t.payments:
            return sum(p.amount_php for p in t.payments if p.status == PaymentStatus.RECEIVED)
        return t.php_amt if t.payment_status != PaymentStatus.PENDING else 0.0

    received = lambda t: t.payment_status != PaymentStatus.PENDING

    # ── By currency ──────────────────────────────────────────────────────
    # Stock quantity flows on physical handover (PENDING included — the rider
    # already gave the FX). PHP and THAN flow only on payment confirmation.

    by_currency: dict[str, dict] = {}
    for t in txns:
        code = t.currency_code
        if code not in by_currency:
            ccy = currencies.get(code)
            by_currency[code] = {
                "code":          code,
                "name":          ccy.name         if ccy else code,
                "flag":          ccy.flag         if ccy else "",
                "category":      ccy.category.value if ccy else "OTHERS",
                "sort_order":    ccy.sort_order    if ccy else 99,
                "decimal_places": ccy.decimal_places if ccy else 4,
                "buy_count":  0, "buy_qty":  0.0, "buy_php":  0.0,
                "sell_count": 0, "sell_qty": 0.0, "sell_php": 0.0,
                "than": 0.0,
                "sell_php_pending": 0.0, "than_pending": 0.0,
            }
        if t.type == "BUY":
            by_currency[code]["buy_count"] += 1
            by_currency[code]["buy_qty"]   += t.foreign_amt
            by_currency[code]["buy_php"]   += _slice_received_php(t)
        else:
            by_currency[code]["sell_count"] += 1
            by_currency[code]["sell_qty"]   += t.foreign_amt
            # Accrual: PENDING SELLs contribute to sell_php / than (matches
            # Ken's Excel grand totals). *_pending split is per-slice, so a
            # half-pending SELL contributes only its pending half to the badge.
            by_currency[code]["sell_php"]   += t.php_amt
            by_currency[code]["than"]       += t.than
            pending_php = _slice_pending_php(t)
            if pending_php > 0:
                by_currency[code]["sell_php_pending"] += pending_php
                if t.php_amt > 0:
                    by_currency[code]["than_pending"] += t.than * (pending_php / t.php_amt)

    # Round float aggregates to 2dp at the response boundary.
    for row in by_currency.values():
        row["buy_php"]          = round(row["buy_php"],          2)
        row["sell_php"]         = round(row["sell_php"],         2)
        row["than"]             = round(row["than"],             2)
        row["sell_php_pending"] = round(row["sell_php_pending"], 2)
        row["than_pending"]     = round(row["than_pending"],     2)

    # Sort: MAIN → 2ND → OTHERS, within each by Ken's Excel column order
    category_order = {"MAIN": 0, "2ND": 1, "OTHERS": 2}
    sorted_currencies = sorted(
        by_currency.values(),
        key=lambda x: (category_order.get(x["category"], 9), x["sort_order"])
    )

    def _comm(t):
        if not t.official_rate:
            return 0.0
        return (t.rate - t.official_rate) * t.foreign_amt if str(t.type) == "SELL" \
            else (t.official_rate - t.rate) * t.foreign_amt

    # ── By cashier ───────────────────────────────────────────────────────
    by_cashier: dict[str, dict] = {}
    for t in txns:
        if not received(t):
            continue
        name = t.cashier
        if name not in by_cashier:
            by_cashier[name] = {
                "cashier":    name,
                "buy_count":  0, "buy_php":  0.0,
                "sell_count": 0, "sell_php": 0.0,
                "than": 0.0, "commission": 0.0,
            }
        if t.type == "BUY":
            by_cashier[name]["buy_count"] += 1
            by_cashier[name]["buy_php"]   += t.php_amt
        else:
            by_cashier[name]["sell_count"] += 1
            by_cashier[name]["sell_php"]   += t.php_amt
            by_cashier[name]["than"]       += t.than
        by_cashier[name]["commission"] += _comm(t)

    # ── Totals ───────────────────────────────────────────────────────────
    # SELL totals + THAN are ACCRUAL (include PENDING) to match Excel grand
    # totals; pending split is reported alongside as a receivables view.
    # BUY total stays RECEIVED-only (PENDING BUY = we owe customer; rare) but
    # is now per-slice so a half-paid BUY counts the received slice.
    total_bought       = sum(_slice_received_php(t) for t in txns if t.type == "BUY")
    total_sold         = sum(t.php_amt for t in txns if t.type == "SELL")
    total_than         = sum(t.than   for t in txns)
    total_commission   = sum(_comm(t) for t in txns if received(t))
    total_sold_pending = sum(_slice_pending_php(t) for t in txns if t.type == "SELL")
    total_than_pending = sum(
        (t.than * (_slice_pending_php(t) / t.php_amt)) if t.php_amt > 0 else 0.0
        for t in txns
    )
    pending_count      = sum(1 for t in txns if _slice_pending_php(t) > 0)

    # ── By payment method (slice-level aggregate) ────────────────────────────
    # Net-new in Phase 4 — one row per method seen today, split by direction
    # (BUY = we paid the customer; SELL = customer paid us). Slice-count, not
    # txn-count: a SELL with 2 slices contributes 2 to its methods' counts.
    method_order = [m.value for m in PaymentMode]
    by_method: dict[str, dict] = {}
    for t in txns:
        for p in t.payments:
            m = p.method.value
            d = by_method.setdefault(m, {
                "method":            m,
                "buy_count":         0,
                "buy_php":           0.0,
                "sell_count":        0,
                "sell_php":          0.0,  # accrual (RECEIVED + PENDING)
                "sell_php_received": 0.0,
                "sell_php_pending":  0.0,
            })
            if t.type.value == "BUY":
                d["buy_count"] += 1
                if p.status == PaymentStatus.RECEIVED:
                    d["buy_php"] += p.amount_php
            else:
                d["sell_count"] += 1
                d["sell_php"]   += p.amount_php
                if p.status == PaymentStatus.RECEIVED:
                    d["sell_php_received"] += p.amount_php
                else:
                    d["sell_php_pending"] += p.amount_php
    by_payment_method = sorted(
        by_method.values(),
        key=lambda x: method_order.index(x["method"]) if x["method"] in method_order else 99,
    )

    # ── Opening positions ────────────────────────────────────────────────────
    raw_positions = db.query(DailyPosition).filter(
        DailyPosition.date == target,
        DailyPosition.carry_in_qty > 0,
    ).all()
    opening_positions = []
    total_opening_stock_php = 0.0
    for p in raw_positions:
        ccy = currencies.get(p.currency_code)
        carry_php = round(p.carry_in_qty * p.carry_in_rate, 2)
        total_opening_stock_php += carry_php
        opening_positions.append({
            "code":           p.currency_code,
            "name":           ccy.name            if ccy else p.currency_code,
            "flag":           ccy.flag            if ccy else "",
            "category":       ccy.category.value  if ccy else "OTHERS",
            "sort_order":     ccy.sort_order       if ccy else 99,
            "decimal_places": ccy.decimal_places   if ccy else 4,
            "carry_in_qty":   p.carry_in_qty,
            "carry_in_rate":  p.carry_in_rate,
            "carry_in_php":   carry_php,
        })
    opening_positions.sort(key=lambda x: (category_order.get(x["category"], 9), x["sort_order"]))
    total_opening_stock_php = round(total_opening_stock_php, 2)

    # ── Stock summary (closing = next day's carry-in) ────────────────────────
    next_date = target + timedelta(days=1)
    closing_pos_map = {
        p.currency_code: p
        for p in db.query(DailyPosition).filter(DailyPosition.date == next_date).all()
    }
    opening_pos_map = {p["code"]: p for p in opening_positions}
    stock_summary = []
    all_codes = set(opening_pos_map) | set(by_currency)
    for code in sorted(all_codes, key=lambda c: (
        category_order.get((currencies.get(c) and currencies[c].category.value) or "OTHERS", 9),
        currencies[c].sort_order if currencies.get(c) else 99,
    )):
        ccy = currencies.get(code)
        op  = opening_pos_map.get(code)
        txn = next((x for x in sorted_currencies if x["code"] == code), None)
        cl  = closing_pos_map.get(code)
        carry_in_qty  = op["carry_in_qty"]  if op  else 0.0
        carry_in_rate = op["carry_in_rate"] if op  else 0.0
        buy_qty  = txn["buy_qty"]  if txn else 0.0
        buy_php  = txn["buy_php"]  if txn else 0.0
        sell_qty = txn["sell_qty"] if txn else 0.0
        closing_qty  = carry_in_qty + buy_qty - sell_qty
        closing_rate = cl.carry_in_rate if cl else 0.0
        closing_php  = round(closing_qty * closing_rate, 2)
        stock_summary.append({
            "code":          code,
            "name":          ccy.name         if ccy else code,
            "flag":          ccy.flag         if ccy else "",
            "category":      ccy.category.value if ccy else "OTHERS",
            "sort_order":    ccy.sort_order    if ccy else 99,
            "decimal_places": ccy.decimal_places if ccy else 4,
            "carry_in_qty":  carry_in_qty,
            "buy_qty":       buy_qty,
            "sell_qty":      sell_qty,
            "closing_qty":   closing_qty,
            "closing_rate":  closing_rate,
            "closing_php":   closing_php,
        })
    total_closing_stock_php = round(sum(s["closing_php"] for s in stock_summary), 2)

    # ── Special credits ──────────────────────────────────────────────────────
    # Disbursements: credits given out today
    credits_today = (
        db.query(SpecialCredit)
        .filter(SpecialCredit.disbursed_date == target)
        .filter(SpecialCredit.status != CreditStatus.CANCELLED)
        .all()
    )
    # Payments received: installments marked paid today
    payments_today = (
        db.query(CreditInstallment)
        .filter(CreditInstallment.paid_at == target)
        .all()
    )
    # Enrich payments with credit info for display
    credit_map = {str(c.id): c for c in db.query(SpecialCredit).all()}
    credit_disbursements = [
        {
            "id":            str(c.id),
            "customer_name": c.customer_name,
            "currency_code": c.currency_code,
            "principal":     c.principal,
            "interest":      c.interest,
            "credit_type":   c.credit_type.value,
            # UPFRONT: cash out = principal - interest (interest kept); INSTALLMENT: cash out = principal
            "cash_out":      round(c.principal - c.interest, 2) if c.credit_type.value == "UPFRONT" else round(c.principal, 2),
        }
        for c in credits_today
    ]
    credit_payments = [
        {
            "installment_id": str(p.id),
            "credit_id":      str(p.credit_id),
            "customer_name":  credit_map[str(p.credit_id)].customer_name if str(p.credit_id) in credit_map else "",
            "currency_code":  credit_map[str(p.credit_id)].currency_code if str(p.credit_id) in credit_map else "",
            "installment_no": p.installment_no,
            "amount":         p.amount,
            "received_by":    p.received_by,
        }
        for p in payments_today
    ]
    total_credit_cash_out  = round(sum(d["cash_out"]  for d in credit_disbursements), 2)
    total_credit_cash_in   = round(sum(p["amount"]    for p in credit_payments), 2)
    # Interest income: from UPFRONT credits disbursed today + interest portion of fully paid INSTALLMENT credits
    interest_income_today  = round(sum(c.interest for c in credits_today if c.credit_type.value == "UPFRONT"), 2)

    # ── Safe movements (PHP vault, signed amounts) ───────────────────────────
    safe_rows = (
        db.query(SafeMovement)
        .filter(SafeMovement.movement_date == target)
        .order_by(SafeMovement.created_at)
        .all()
    )
    safe_movements = [
        {
            "id":             str(m.id),
            "amount_php":     m.amount_php,
            "reason":         m.reason,
            "note":           m.note,
            "actor_username": m.actor_username,
            "created_at":     m.created_at.isoformat() if m.created_at else None,
        }
        for m in safe_rows
    ]
    safe_today_net = round(sum(m.amount_php for m in safe_rows), 2)

    # ── Peso (treasurer drawer bookends + breakdown) ────────────────────────
    # Opening = earliest treasurer shift on this date (opening_cash_php).
    # Closing = latest treasurer shift's declared closing_cash_php, falling
    # back to expected_cash_php while still open. Treasurer = User.role==supervisor.
    # Breakdown components mirror _treasurer_aggregates in shifts.py but rolled
    # up to the daily level so a single peso flow row can show OPEN + SOLD −
    # BOUGHT + BALE − RETURNS + CHEQUES − EXPENSES = CLOSE.
    treasurer_username_list = [u for (u,) in db.query(User.username).filter(User.role == UserRole.supervisor).all()]
    treasurer_shifts = (
        db.query(TellerShift)
        .filter(TellerShift.date == target)
        .filter(TellerShift.cashier.in_(treasurer_username_list))
        .order_by(TellerShift.opened_at)
        .all()
    ) if treasurer_username_list else []
    if treasurer_shifts:
        opening_php = round(treasurer_shifts[0].opening_cash_php or 0.0, 2)
        last = treasurer_shifts[-1]
        closing_raw = last.closing_cash_php if last.closing_cash_php is not None else last.expected_cash_php
        closing_php = round(closing_raw, 2) if closing_raw is not None else None
    else:
        opening_php = None
        closing_php = None
    # Live flag only flips True after we've computed the live projection below.
    closing_is_live = False

    if treasurer_username_list:
        treasurer_shift_ids = [s.id for s in treasurer_shifts]
        bale_php = round(sum(
            r.amount_php for r in db.query(CashReplenishment)
            .filter(CashReplenishment.shift_id.in_(treasurer_shift_ids))
            .filter(CashReplenishment.source == "SAFE")
            .all()
        ), 2) if treasurer_shift_ids else 0.0
        inter_branch_in_php = round(sum(
            r.amount_php for r in db.query(CashReplenishment)
            .filter(CashReplenishment.shift_id.in_(treasurer_shift_ids))
            .filter(CashReplenishment.source == "INTER_BRANCH")
            .all()
        ), 2) if treasurer_shift_ids else 0.0
        # Signed net of treasurer-actor vault movements: + = drawer→vault deposit,
        # − = vault→drawer withdrawal. Formula subtracts this so withdrawals add
        # to closing peso (cash arrived in drawer) and deposits subtract (cash left).
        vault_returns_php = round(sum(
            m.amount_php for m in db.query(SafeMovement)
            .filter(SafeMovement.movement_date == target)
            .filter(SafeMovement.actor_username.in_(treasurer_username_list))
            .all()
        ), 2)
        expenses_php = round(sum(
            e.amount_php for e in db.query(Expense)
            .filter(Expense.date == target)
            .filter(Expense.shift_id.is_(None))
            .filter(Expense.recorded_by.in_(treasurer_username_list))
            .filter(Expense.status != ExpenseStatus.REJECTED)
            .all()
        ), 2)
        cheques_cleared_php = round(sum(
            p.amount_php for p in db.query(TxnPayment)
            .filter(TxnPayment.method == PaymentMode.CHEQUE)
            .filter(TxnPayment.cleared_at.isnot(None))
            .filter(func.date(TxnPayment.cleared_at) == target)
            .filter(TxnPayment.cleared_by.in_(treasurer_username_list))
            .all()
        ), 2)
        rider_remits_php = round(sum(
            d.remit_php or 0 for d in db.query(RiderDispatch)
            .filter(RiderDispatch.date == target)
            .filter(RiderDispatch.status.in_([DispatchStatus.REMITTED, DispatchStatus.RETURNED]))
            .all()
        ), 2)
        dispatched_out_php = round(sum(
            d.cash_php or 0 for d in db.query(RiderDispatch)
            .filter(RiderDispatch.date == target)
            .filter(RiderDispatch.dispatched_by.in_(treasurer_username_list))
            .all()
        ), 2)
        candidate_closes = (
            db.query(TellerShift)
            .filter(TellerShift.date == target)
            .filter(TellerShift.status == ShiftStatus.CLOSED)
            .filter(~TellerShift.cashier.in_(treasurer_username_list))
            .all()
        )
        last_per_terminal = []
        for cs in candidate_closes:
            later = (
                db.query(TellerShift)
                .filter(TellerShift.id != cs.id)
                .filter(TellerShift.date == cs.date)
                .filter(TellerShift.terminal_id == cs.terminal_id)
                .filter(TellerShift.opened_at > cs.opened_at)
                .first()
            )
            if later is None:
                last_per_terminal.append(cs)
        from_cashier_php = round(sum(s.closing_cash_php or 0 for s in last_per_terminal), 2)
    else:
        bale_php = 0.0
        inter_branch_in_php = 0.0
        vault_returns_php = 0.0
        expenses_php = 0.0
        cheques_cleared_php = 0.0
        rider_remits_php = 0.0
        dispatched_out_php = 0.0
        from_cashier_php = 0.0

    # Live closing fallback: when a treasurer shift exists but isn't closed yet
    # (no closing_cash_php and no expected_cash_php written), project the closing
    # from the same breakdown components the report shows. Same formula as the
    # supervisor screen so the figure matches what Eunice/Merly see live.
    if treasurer_shifts and closing_php is None:
        closing_php = compute_expected_cash_treasurer(
            opening_cash=opening_php or 0.0,
            from_dispatches=rider_remits_php,
            dispatches_out=dispatched_out_php,
            from_cashier=from_cashier_php,
            bale_peso=bale_php,
            inter_branch_in=inter_branch_in_php,
            vault_returns=vault_returns_php,
            expenses=expenses_php,
            cheques_cleared=cheques_cleared_php,
        )
        closing_is_live = True

    return {
        "date":               str(target),
        "generated_at":       datetime.now().strftime("%I:%M %p"),
        "total_transactions":  len(txns),
        "total_bought_php":        round(total_bought,         2),
        "total_sold_php":          round(total_sold,           2),
        "total_than":              round(total_than,           2),
        "total_commission":        round(total_commission,     2),
        "total_sold_php_pending":  round(total_sold_pending,   2),
        "total_than_pending":      round(total_than_pending,   2),
        "pending_count":           pending_count,
        "opening_positions":        opening_positions,
        "total_opening_stock_php":  total_opening_stock_php,
        "stock_summary":            stock_summary,
        "total_closing_stock_php":  total_closing_stock_php,
        "by_currency":        sorted_currencies,
        "by_cashier":         sorted(by_cashier.values(), key=lambda x: x["cashier"]),
        "by_payment_method":  [
            {**d, "buy_php": round(d["buy_php"], 2), "sell_php": round(d["sell_php"], 2),
             "sell_php_received": round(d["sell_php_received"], 2),
             "sell_php_pending": round(d["sell_php_pending"], 2)}
            for d in by_payment_method
        ],
        "special_credits": {
            "disbursements":       credit_disbursements,
            "payments":            credit_payments,
            "total_cash_out":      total_credit_cash_out,
            "total_cash_in":       total_credit_cash_in,
            "interest_income":     interest_income_today,
        },
        "safe": {
            "movements": safe_movements,
            "today_net": safe_today_net,
        },
        "peso": {
            "opening_php": opening_php,
            "closing_php": closing_php,
            "closing_is_live": closing_is_live,
            "bale_php": bale_php,
            "inter_branch_in_php": inter_branch_in_php,
            "vault_returns_php": vault_returns_php,
            "cheques_cleared_php": cheques_cleared_php,
            "expenses_php": expenses_php,
            "rider_remits_php": rider_remits_php,
            "dispatched_out_php": dispatched_out_php,
            "from_cashier_php": from_cashier_php,
        },
        "transactions": [
            {
                "id":          t.id,
                "time":        t.time,
                "type":        t.type.value,
                "source":      t.source.value,
                "currency":    t.currency_code,
                "foreign_amt": t.foreign_amt,
                "rate":        t.rate,
                "php_amt":     t.php_amt,
                "than":        t.than,
                "cashier":     t.cashier,
                "customer":    t.customer or "",
                "payment_status": t.payment_status.value if hasattr(t.payment_status, 'value') else (t.payment_status or "RECEIVED"),
                "payments": [
                    {
                        "id":           str(p.id),
                        "method":       p.method.value,
                        "amount_php":   p.amount_php,
                        "status":       p.status.value,
                        "reference_no": p.reference_no,
                        "received_at":  p.received_at.isoformat() if p.received_at else None,
                        "confirmed_by": p.confirmed_by,
                    }
                    for p in t.payments
                ],
            }
            for t in txns
        ],
    }
