"""
BSP regulatory reports. Phase 1: Quarterly MC/FX Volume Report (Circular 1222).

Source: app.models.transaction.Transaction. BUY + SELL in PHP (php_amt) only;
EXCESS is excluded because no peso changes hands. All payment statuses count
(PENDING + RECEIVED) — the deal happened on the txn date regardless of when
the money clears.

Admin-only. Regulatory reports are not delegated to treasurer/cashier.
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.today import get_today
from app.models.transaction import Transaction
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/bsp", tags=["bsp"])

# Type-F threshold per BSP Circular 1222: monthly volume <₱50M AND capital <₱10M
# triggers AFS-to-BSP exemption.
TYPE_F_MONTHLY_THRESHOLD_PHP = 50_000_000.0


def _quarter_range(year: int, quarter: int) -> tuple[date, date]:
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(400, f"Invalid quarter: {quarter}")
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def _filing_deadline(quarter_end: date) -> date:
    """10 business days after quarter-end (skip weekends)."""
    d = quarter_end
    added = 0
    while added < 10:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def _quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _flatten(buckets: dict, key_name: str) -> list:
    out = []
    for k in sorted(buckets.keys()):
        v = buckets[k]
        out.append({
            key_name: k,
            "buy_count":   v["buy_count"],
            "buy_php":     round(v["buy_php"], 2),
            "sell_count":  v["sell_count"],
            "sell_php":    round(v["sell_php"], 2),
            "total_count": v["buy_count"] + v["sell_count"],
            "total_php":   round(v["buy_php"] + v["sell_php"], 2),
        })
    return out


@router.get("/quarterly-volume")
async def get_quarterly_volume(
    year:    Optional[int] = Query(None, ge=2020, le=2100),
    quarter: Optional[int] = Query(None, ge=1, le=4),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Quarterly MC/FX Volume Report. Defaults to the current calendar quarter.
    Filters: type IN (BUY, SELL); EXCESS excluded; all payment statuses.
    """
    today = get_today()
    if year is None:    year    = today.year
    if quarter is None: quarter = _quarter_of(today)

    start, end = _quarter_range(year, quarter)
    is_current = start <= today <= end

    rows = db.query(Transaction).filter(
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.type.in_(["BUY", "SELL"]),
    ).all()

    def _empty(): return {"buy_count": 0, "buy_php": 0.0, "sell_count": 0, "sell_php": 0.0}
    by_currency = defaultdict(_empty)
    by_branch   = defaultdict(_empty)
    by_month    = defaultdict(_empty)

    buy_count = sell_count = 0
    buy_php = sell_php = 0.0

    for r in rows:
        php = r.php_amt or 0.0
        m   = r.date.strftime("%Y-%m")
        b   = r.branch_id or "—"
        c   = r.currency_code
        if r.type == "BUY":
            buy_count += 1
            buy_php   += php
            by_currency[c]["buy_count"] += 1; by_currency[c]["buy_php"] += php
            by_branch[b]["buy_count"]   += 1; by_branch[b]["buy_php"]   += php
            by_month[m]["buy_count"]    += 1; by_month[m]["buy_php"]    += php
        else:
            sell_count += 1
            sell_php   += php
            by_currency[c]["sell_count"] += 1; by_currency[c]["sell_php"] += php
            by_branch[b]["sell_count"]   += 1; by_branch[b]["sell_php"]   += php
            by_month[m]["sell_count"]    += 1; by_month[m]["sell_php"]    += php

    return {
        "period": {
            "year":             year,
            "quarter":          quarter,
            "from":             start.isoformat(),
            "to":               end.isoformat(),
            "is_current":       is_current,
            "filing_deadline":  None if is_current else _filing_deadline(end).isoformat(),
        },
        "totals": {
            "buy_count":    buy_count,
            "buy_php":      round(buy_php, 2),
            "sell_count":   sell_count,
            "sell_php":     round(sell_php, 2),
            "total_count":  buy_count + sell_count,
            "total_php":    round(buy_php + sell_php, 2),
        },
        "by_currency": _flatten(by_currency, "currency"),
        "by_branch":   _flatten(by_branch,   "branch_id"),
        "by_month":    _flatten(by_month,    "month"),
    }


@router.get("/monthly-volume")
async def get_monthly_volume(
    months: int = Query(12, ge=1, le=36),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Rolling N-month volume series for Type-F threshold check (₱50M/month).
    UI overlays the threshold line so Ken can see at a glance whether AFS
    submission is required.
    """
    today = get_today()

    start_month = today.month - months + 1
    start_year  = today.year
    while start_month <= 0:
        start_month += 12
        start_year  -= 1
    start = date(start_year, start_month, 1)

    rows = db.query(Transaction).filter(
        Transaction.date >= start,
        Transaction.date <= today,
        Transaction.type.in_(["BUY", "SELL"]),
    ).all()

    by_month: dict[str, float] = defaultdict(float)
    for r in rows:
        by_month[r.date.strftime("%Y-%m")] += r.php_amt or 0.0

    series: list = []
    y, m = start_year, start_month
    while date(y, m, 1) <= date(today.year, today.month, 1):
        key = f"{y:04d}-{m:02d}"
        v   = round(by_month.get(key, 0.0), 2)
        series.append({
            "month":         key,
            "total_php":     v,
            "above_type_f":  v >= TYPE_F_MONTHLY_THRESHOLD_PHP,
        })
        m += 1
        if m > 12:
            m = 1
            y += 1

    months_above = sum(1 for s in series if s["above_type_f"])
    avg          = sum(s["total_php"] for s in series) / len(series) if series else 0.0

    return {
        "threshold_php":         TYPE_F_MONTHLY_THRESHOLD_PHP,
        "months_above":          months_above,
        "average_monthly_php":   round(avg, 2),
        "currently_type_f":      months_above == 0,
        "series":                series,
    }
