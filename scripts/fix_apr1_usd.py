"""
One-off script: fix April 1 2026 USD THAN corruption.

Root cause: OR-84F1F6A9 — March 31 carry-in (26,088 USD @ 60.80) was manually
entered as a BUY before DailyPosition existed. _get_daily_avg double-counted the
carry-in, inflating daily_avg to ~60.77. All 6 USD sells got wrong THAN values.

Steps:
  1. Delete the phantom BUY (OR-84F1F6A9)
  2. Recalculate THAN for the 6 USD sells using correct avg = 60.25 (STOCKSLEFT rate)
  3. Print before/after, commit

Run once from /root/projects/api:
  /root/projects/api/.venv/bin/python3 scripts/fix_apr1_usd.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.core.database import SessionLocal
from app.models.transaction import Transaction

PHANTOM_ID = "OR-84F1F6A9"
FIX_DATE = date(2026, 4, 1)
CORRECT_AVG = 60.25


def main():
    db = SessionLocal()
    try:
        # Step 1: confirm phantom BUY exists
        phantom = db.query(Transaction).filter_by(id=PHANTOM_ID).first()
        if not phantom:
            print(f"ABORT: {PHANTOM_ID} not found — already deleted or wrong date?")
            return
        print(f"Found phantom: {phantom.id} | {phantom.type} | {phantom.foreign_amt} {phantom.currency_code} @ {phantom.rate} | avg={phantom.daily_avg_cost}")

        # Step 2: show current USD SELL THAN for April 1
        sells = db.query(Transaction).filter_by(
            date=FIX_DATE, currency_code="USD", type="SELL"
        ).order_by(Transaction.created_at).all()

        print(f"\n{'='*60}")
        print(f"{'ID':<15} {'Qty':>8} {'Rate':>7} {'Avg':>7} {'THAN (before)':>14}")
        total_before = 0.0
        for s in sells:
            total_before += s.than or 0.0
            print(f"{s.id:<15} {s.foreign_amt:>8} {s.rate:>7} {s.daily_avg_cost:>7} {(s.than or 0):>14.2f}")
        print(f"{'TOTAL':>44} {total_before:>14.2f}")

        # Step 3: apply fix
        db.delete(phantom)

        total_after = 0.0
        for s in sells:
            new_than = round((s.rate - CORRECT_AVG) * s.foreign_amt, 2)
            s.daily_avg_cost = CORRECT_AVG
            s.than = new_than
            total_after += new_than

        print(f"\n{'='*60}")
        print(f"{'ID':<15} {'Qty':>8} {'Rate':>7} {'Avg':>7} {'THAN (after)':>13}")
        for s in sells:
            print(f"{s.id:<15} {s.foreign_amt:>8} {s.rate:>7} {s.daily_avg_cost:>7} {s.than:>13.2f}")
        print(f"{'TOTAL':>44} {total_after:>13.2f}")
        print(f"\nExpected total: ~+10,616.60")
        print(f"Phantom BUY {PHANTOM_ID} will be deleted.")

        confirm = input("\nCommit these changes? (yes/no): ").strip().lower()
        if confirm == "yes":
            db.commit()
            print("Done. DB updated.")
        else:
            db.rollback()
            print("Rolled back. No changes made.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
