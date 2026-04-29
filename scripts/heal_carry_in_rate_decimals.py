"""
Round daily_positions.carry_in_rate to currency.decimal_places.

Background: prior to the eod.py fix on 2026-04-29, the EOD close stamped
result.daily_avg_cost (raw weighted-avg float, full float64 precision) into
tomorrow's daily_positions.carry_in_rate. That made the next day's daily
report show funny rates like USD 59.36119190481033 instead of 59.36, and
total_closing_stock_php drifted by ₱thousands.

This script rounds every dirty carry_in_rate to its currency's decimal_places
(the canonical precision stored on currencies.decimal_places). It writes an
audit log of (date, code, old_rate, new_rate) so the change is reversible.

Generic by design: takes a date, finds rows whose carry_in_rate has more
decimals than the currency allows, rounds them. Reusable for any future
incident.

Usage:
    .venv/bin/python -m scripts.heal_carry_in_rate_decimals 2026-04-24 --dry-run
    .venv/bin/python -m scripts.heal_carry_in_rate_decimals 2026-04-24 --apply
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.models.currency import Currency, DailyPosition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_date", type=lambda s: date.fromisoformat(s))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        currency_dp = {c.code: c.decimal_places for c in db.query(Currency).all()}
        rows = db.query(DailyPosition).filter(DailyPosition.date == args.target_date).all()

        changes = []
        for r in rows:
            dp = currency_dp.get(r.currency_code, 4)
            old = r.carry_in_rate
            new = round(old, dp)
            if old != new:
                changes.append({
                    "row": r,
                    "date": str(r.date),
                    "currency_code": r.currency_code,
                    "decimal_places": dp,
                    "old_rate": old,
                    "new_rate": new,
                    "delta": new - old,
                })

        if not changes:
            print(f"No rounding needed for {args.target_date}.")
            return 0

        print(f"\n{len(changes)} rows need rounding:\n")
        for c in changes:
            print(
                f"  {c['currency_code']:4} ({c['decimal_places']}dp)  "
                f"{c['old_rate']:<22}  →  {c['new_rate']}"
            )

        if args.dry_run:
            print("\n(dry-run — no DB changes)")
            return 0

        audit_dir = Path(__file__).parent / "audit"
        audit_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit_path = audit_dir / f"carry_in_rate_heal_{args.target_date}_{stamp}.json"
        audit_path.write_text(json.dumps(
            [{k: v for k, v in c.items() if k != "row"} for c in changes],
            indent=2,
        ))

        for c in changes:
            c["row"].carry_in_rate = c["new_rate"]
        db.commit()

        print(f"\nApplied {len(changes)} updates. Audit: {audit_path}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
