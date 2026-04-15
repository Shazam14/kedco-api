from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime
from typing import Optional

from app.core.database import get_db
from app.models.transaction import Transaction
from app.models.currency import Currency
from app.models.user import User
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
                "decimal_places": ccy.decimal_places if ccy else 4,
                "buy_count":  0, "buy_qty":  0.0, "buy_php":  0.0,
                "sell_count": 0, "sell_qty": 0.0, "sell_php": 0.0,
                "than": 0.0,
            }
        if t.type == "BUY":
            by_currency[code]["buy_count"] += 1
            by_currency[code]["buy_qty"]   += t.foreign_amt
            by_currency[code]["buy_php"]   += t.php_amt
        else:
            by_currency[code]["sell_count"] += 1
            by_currency[code]["sell_qty"]   += t.foreign_amt
            by_currency[code]["sell_php"]   += t.php_amt
            by_currency[code]["than"]       += t.than

    # Sort: MAIN first, then 2ND, then OTHERS; within each, by most activity
    category_order = {"MAIN": 0, "2ND": 1, "OTHERS": 2}
    sorted_currencies = sorted(
        by_currency.values(),
        key=lambda x: (category_order.get(x["category"], 9), -(x["buy_php"] + x["sell_php"]))
    )

    # ── By cashier ───────────────────────────────────────────────────────
    by_cashier: dict[str, dict] = {}
    for t in txns:
        name = t.cashier
        if name not in by_cashier:
            by_cashier[name] = {
                "cashier":    name,
                "buy_count":  0, "buy_php":  0.0,
                "sell_count": 0, "sell_php": 0.0,
                "than": 0.0,
            }
        if t.type == "BUY":
            by_cashier[name]["buy_count"] += 1
            by_cashier[name]["buy_php"]   += t.php_amt
        else:
            by_cashier[name]["sell_count"] += 1
            by_cashier[name]["sell_php"]   += t.php_amt
            by_cashier[name]["than"]       += t.than

    # ── Totals ───────────────────────────────────────────────────────────
    total_bought = sum(t.php_amt for t in txns if t.type == "BUY")
    total_sold   = sum(t.php_amt for t in txns if t.type == "SELL")
    total_than   = sum(t.than   for t in txns)

    return {
        "date":               str(target),
        "generated_at":       datetime.now().strftime("%I:%M %p"),
        "total_transactions": len(txns),
        "total_bought_php":   round(total_bought, 2),
        "total_sold_php":     round(total_sold,   2),
        "total_than":         round(total_than,   2),
        "by_currency":        sorted_currencies,
        "by_cashier":         sorted(by_cashier.values(), key=lambda x: x["cashier"]),
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
            }
            for t in txns
        ],
    }
