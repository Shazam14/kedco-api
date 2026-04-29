"""
Recompute THAN for all SELL transactions on a given date using the FULL-DAY
weighted-average cost — Ken's documented rule (see forex.py:50).

Why this exists: `transactions.create_transaction` stamps daily_avg_cost at the
moment the SELL is inserted, using whatever BUYs exist in the DB at that
instant. When we seed historical days in batches (or out of chronological
order), each SELL ends up with a different partial-day avg. Excel uses one
full-day avg uniformly. This brings the DB in line with Excel.

Long-term plan: EOD re-stamps all SELLs the same way, so this script becomes
unnecessary for new dates.

Usage:
    .venv/bin/python -m scripts.recompute_than 2026-04-23 --dry-run
    .venv/bin/python -m scripts.recompute_than 2026-04-23 --apply
"""
import argparse
import sys
from datetime import date as date_type
from collections import defaultdict

from app.core.database import SessionLocal
from app.models.transaction import Transaction, TxnType
from app.models.currency import DailyPosition, Currency
from app.models.customer import Customer  # noqa: F401  — resolves transactions.customer_id FK
from app.services.forex import CarryIn, TodayBuy, compute_position


def recompute(target: date_type, apply: bool) -> int:
    db = SessionLocal()
    try:
        txns = (
            db.query(Transaction)
            .filter(Transaction.date == target)
            .order_by(Transaction.currency_code, Transaction.created_at)
            .all()
        )
        if not txns:
            print(f"No transactions on {target}.")
            return 0

        positions = {
            p.currency_code: p
            for p in db.query(DailyPosition).filter(DailyPosition.date == target).all()
        }
        # Round daily_avg to currency.decimal_places before stamping THAN —
        # mirrors Ken's Excel methodology (display-precision rounding pre-THAN).
        decimals = {c.code: c.decimal_places for c in db.query(Currency).all()}

        # Group by currency
        by_curr: dict[str, list[Transaction]] = defaultdict(list)
        for t in txns:
            by_curr[t.currency_code].append(t)

        changed_rows = 0
        for ccy, ccy_txns in sorted(by_curr.items()):
            pos = positions.get(ccy)
            if not pos:
                # No carry-in on file → can't compute avg. Skip.
                print(f"  [skip] {ccy}: no DailyPosition for {target}")
                continue

            buys = [
                TodayBuy(qty=t.foreign_amt, rate=t.rate)
                for t in ccy_txns
                if t.type in (TxnType.BUY, TxnType.EXCESS)
            ]
            sells = [t for t in ccy_txns if t.type == TxnType.SELL]
            if not sells:
                continue

            # Sell-rate input is unused for THAN — pass any value (sell_rate
            # affects unrealized only). Ken's rule: avg uses carry + buys.
            result = compute_position(
                CarryIn(qty=pos.carry_in_qty, rate=pos.carry_in_rate),
                buys,
                today_sell_rate=0.0,
            )
            dp = decimals.get(ccy, 4)
            full_day_avg = round(result.daily_avg_cost, dp)

            print(f"\n{ccy}: full-day avg = {result.daily_avg_cost:.6f} "
                  f"→ rounded to {dp}dp = {full_day_avg}  "
                  f"(carry {pos.carry_in_qty}@{pos.carry_in_rate}, buys={len(buys)}, sells={len(sells)})")

            for s in sells:
                old_avg = s.daily_avg_cost
                old_than = s.than or 0.0
                new_than = round((s.rate - full_day_avg) * s.foreign_amt, 2)
                delta = new_than - old_than

                if abs(delta) < 0.01 and abs(old_avg - full_day_avg) < 1e-9:
                    continue  # already correct

                print(f"  {s.id:<14} qty={s.foreign_amt:>10}  rate={s.rate:>8}  "
                      f"avg {old_avg:>10.6f} → {full_day_avg:>10.6f}   "
                      f"than {old_than:>10.2f} → {new_than:>10.2f}  (Δ {delta:+.2f})")

                if apply:
                    s.daily_avg_cost = full_day_avg
                    s.than = new_than
                changed_rows += 1

        if apply:
            db.commit()
            print(f"\n✓ Committed {changed_rows} row update(s).")
        else:
            print(f"\n(dry-run) {changed_rows} row(s) would be updated.")
        return changed_rows
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="ISO date, e.g. 2026-04-23")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    target = date_type.fromisoformat(args.date)
    recompute(target, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
