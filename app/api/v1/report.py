from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime, timedelta
from typing import Optional

from app.core.database import get_db
from app.models.transaction import Transaction, PaymentStatus
from app.models.currency import Currency, DailyPosition
from app.models.user import User
from app.models.credit import SpecialCredit, CreditInstallment, CreditStatus
from app.api.v1.auth import require_role, TokenData

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
    target = report_date or date_type.today()

    demo_users = db.query(User.username).filter(User.is_demo == True).scalar_subquery()
    txns = (
        db.query(Transaction)
        .filter(Transaction.date == target)
        .filter(~Transaction.cashier.in_(demo_users))
        .order_by(Transaction.created_at)
        .all()
    )

    currencies = {c.code: c for c in db.query(Currency).all()}

    # ── By currency ─────────────────��────────────────────────────────────
    # Stock quantity flows on physical handover (PENDING included — the rider
    # already gave the FX). PHP and THAN flow only on payment confirmation, so
    # those fields stay filtered to RECEIVED.
    received = lambda t: t.payment_status != PaymentStatus.PENDING

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
            if received(t):
                by_currency[code]["buy_php"] += t.php_amt
        else:
            by_currency[code]["sell_count"] += 1
            by_currency[code]["sell_qty"]   += t.foreign_amt
            # Accrual: PENDING SELLs contribute to sell_php / than (matches
            # Ken's Excel grand totals). Surface separately as *_pending so the
            # frontend can show a [⏳ pending: ₱X] receivables badge.
            by_currency[code]["sell_php"]   += t.php_amt
            by_currency[code]["than"]       += t.than
            if not received(t):
                by_currency[code]["sell_php_pending"] += t.php_amt
                by_currency[code]["than_pending"]     += t.than

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
    # BUY total stays RECEIVED-only (PENDING BUY = we owe customer; rare).
    total_bought       = sum(t.php_amt for t in txns if t.type == "BUY" and received(t))
    total_sold         = sum(t.php_amt for t in txns if t.type == "SELL")
    total_than         = sum(t.than   for t in txns)
    total_commission   = sum(_comm(t) for t in txns if received(t))
    total_sold_pending = sum(t.php_amt for t in txns if t.type == "SELL" and not received(t))
    total_than_pending = sum(t.than   for t in txns if not received(t))
    pending_count      = sum(1 for t in txns if not received(t))

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
        "special_credits": {
            "disbursements":       credit_disbursements,
            "payments":            credit_payments,
            "total_cash_out":      total_credit_cash_out,
            "total_cash_in":       total_credit_cash_in,
            "interest_income":     interest_income_today,
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
            }
            for t in txns
        ],
    }
