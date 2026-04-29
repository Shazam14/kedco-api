"""
One-off heal for April 23 BUY rates: align DB to Ken's Excel record so the
day reconciles cleanly. Cashiers had typed lower rates than the rate-board
that Excel records; aligning them lets us validate the daily report end-to-end.

Strategy:
  • Per (qty, cashier-typed-rate, excel-rate) mapping, update the DB row's
    `rate` and recompute `php_amt`.
  • Save every (id, old_rate, old_php, new_rate, new_php, currency) to
    scripts/audit/apr23_rate_corrections.json so the original cashier input
    is preserved and reversible.
  • Caller is expected to run scripts/recompute_than.py --apply after this.

Usage:
    .venv/bin/python -m scripts.heal_apr23_rates --dry-run
    .venv/bin/python -m scripts.heal_apr23_rates --apply
"""
import argparse
import json
import sys
from datetime import datetime, date as date_type
from pathlib import Path

from app.core.database import SessionLocal
from app.models.transaction import Transaction
from app.models.customer import Customer  # noqa: F401  — resolves transactions.customer_id FK


# (txn_id, new_rate). All for date=2026-04-23.
# Mapping derived by lining up DB rows against Ken's 4.23.26.xlsx BUY x MAIN /
# BUY x OTHERS sheets. Where multiple DB rows shared the same qty (e.g. two
# USD 100 rows at rate=58 vs Excel's 1 at 58 + 3 at 59), the earliest-created
# row was selected to flip — arbitrary but deterministic.
CORRECTIONS: list[tuple[str, float]] = [
    # USD — 14 rows (cashier typed -1 from Excel rate-board)
    ("OR-23D8AB94", 59.0),    # 20  USD: 58 → 59
    ("OR-01E09D4A", 58.0),    # 50  USD: 57 → 58
    ("OR-D549C124", 59.0),    # 100 USD: 58 → 59 (only this 100-qty row flips; OR-0CAA2B94 stays at 58)
    ("OR-5A6C7983", 59.0),    # 250 USD: 58 → 59
    ("OR-AA495B08", 59.0),    # 300 USD: 58 → 59
    ("OR-8B446F80", 59.0),    # 400 USD: 58 → 59
    ("OR-4FC8A92A", 59.0),    # 500 USD: 58 → 59
    ("OR-F6B05B24", 59.0),    # 800 USD: 58 → 59
    ("OR-6FD04694", 59.0),    # 800 USD: 58 → 59
    ("OR-E179EABB", 59.0),    # 1000 USD: 58 → 59
    ("OR-CDDB1758", 59.0),    # 1000 USD: 58 → 59
    ("OR-F79072B5", 59.0),    # 1270 USD: 58 → 59
    ("OR-7DE346A8", 59.0),    # 1400 USD: 58 → 59
    ("OR-7F11A707", 59.0),    # 2500 USD: 58 → 59
    # JPY — 6 rows
    ("OR-A5E0C8A6", 0.372),   # 15000  JPY: 0.36 → 0.372
    ("OR-C16833F3", 0.37),    # 40000  JPY: 0.36 → 0.37
    ("OR-0B898A5E", 0.372),   # 50000  JPY: 0.36 → 0.372
    ("OR-ADE35746", 0.37),    # 120000 JPY: 0.36 → 0.37
    ("OR-B07D9D0E", 0.37),    # 150000 JPY: 0.36 → 0.37
    ("OR-E28339D9", 0.37),    # 310000 JPY: 0.35 → 0.37
    # VND — 1 row
    ("OR-AAEC03E8", 0.002),   # 3,818,000 VND: 0.0018 → 0.002
]

AUDIT_PATH = Path(__file__).resolve().parent / "audit" / "apr23_rate_corrections.json"
EXPECTED_DATE = date_type(2026, 4, 23)


def heal(apply: bool) -> int:
    db = SessionLocal()
    try:
        audit_entries: list[dict] = []
        problems: list[str] = []

        for txn_id, new_rate in CORRECTIONS:
            t = db.query(Transaction).filter(Transaction.id == txn_id).first()
            if t is None:
                problems.append(f"  MISSING: {txn_id}")
                continue
            if t.date != EXPECTED_DATE:
                problems.append(f"  WRONG DATE: {txn_id} is {t.date}, expected {EXPECTED_DATE}")
                continue
            if t.type.value != "BUY":
                problems.append(f"  NOT A BUY: {txn_id} is {t.type.value}")
                continue

            old_rate = t.rate
            old_php  = t.php_amt
            new_php  = round(t.foreign_amt * new_rate, 2)

            audit_entries.append({
                "id":            t.id,
                "currency":      t.currency_code,
                "foreign_amt":   t.foreign_amt,
                "cashier":       t.cashier,
                "rate_old":      old_rate,
                "rate_new":      new_rate,
                "php_amt_old":   old_php,
                "php_amt_new":   new_php,
                "delta_php":     round(new_php - old_php, 2),
            })

            print(f"  {t.id}  {t.currency_code:>3}  qty={t.foreign_amt:>10}  "
                  f"rate {old_rate:>7} → {new_rate:>7}   "
                  f"php {old_php:>10.2f} → {new_php:>10.2f}  ({t.cashier})")

            if apply:
                t.rate = new_rate
                t.php_amt = new_php

        if problems:
            print("\n!! Problems found — aborting:")
            for p in problems: print(p)
            return 1

        total_delta = sum(e["delta_php"] for e in audit_entries)
        print(f"\nTotal PHP shift across {len(audit_entries)} rows: ₱{total_delta:+,.2f}")

        if apply:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            log = {
                "applied_at":  datetime.utcnow().isoformat() + "Z",
                "target_date": EXPECTED_DATE.isoformat(),
                "reason":      "Align cashier-typed rates to Ken's Excel rate-board for daily report tally.",
                "entries":     audit_entries,
                "total_delta_php": round(total_delta, 2),
            }
            AUDIT_PATH.write_text(json.dumps(log, indent=2))
            db.commit()
            print(f"\n✓ Applied {len(audit_entries)} updates")
            print(f"✓ Audit log: {AUDIT_PATH}")
        else:
            print(f"\n(dry-run) {len(audit_entries)} rows would be updated.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.exit(heal(apply=args.apply))
