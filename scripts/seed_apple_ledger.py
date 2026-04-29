"""
Seed Apple's per-row credit ledger from Apple 2026.xlsx.

Reads JAN2026 + FEB2026 sheets (Jan 29 → Apr 11, 2026).
One CreditLedgerEntry per movement row (palod / than / bayad).
Forward-fills blank date cells (Excel inherits date from row above).

Idempotent — if Apple already has ledger rows, exits without doing anything.
Apple's SpecialCredit summary row must already exist (run seed_apple_credit.py first).

Verify totals match the existing summary:
  PALOD ≈ 8,518,557 | THAN ≈ 1,091,871 | BAYAD ≈ 6,111,465
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
from datetime import date, datetime
import openpyxl

from app.core.database import SessionLocal
from app.models.credit import SpecialCredit, CreditLedgerEntry


XLSX = "/root/projects/Apple 2026.xlsx"
SHEETS = ["JAN2026", "FEB2026"]


def parse_movement_rows(ws):
    """Yield dicts for rows where at least one of palod/than/bayad is set."""
    last_date = None
    out = []
    for r in ws.iter_rows(values_only=True):
        d, t, desc, palod, than, bayad, bal = (r + (None,) * 7)[:7]
        if isinstance(d, str) and d.upper() == "DATE":
            continue
        if isinstance(d, datetime):
            d = d.date(); last_date = d
        elif isinstance(d, date):
            last_date = d
        else:
            d = last_date
        if palod is None and than is None and bayad is None:
            continue
        out.append({
            "date":        d,
            "time":        str(t) if t is not None else None,
            "description": str(desc) if desc is not None else None,
            "palod":       float(palod or 0),
            "than":        float(than  or 0),
            "bayad":       float(bayad or 0),
            "balance":     float(bal) if bal is not None else None,
        })
    return out


def main():
    db = SessionLocal()
    try:
        apple = db.query(SpecialCredit).filter_by(customer_name="Apple").first()
        if apple is None:
            print("!! Apple SpecialCredit row not found. Run seed_apple_credit.py first.")
            sys.exit(1)

        existing = db.query(CreditLedgerEntry).filter_by(credit_id=apple.id).count()
        if existing > 0:
            print(f"Apple already has {existing} ledger rows — skipping.")
            return

        wb = openpyxl.load_workbook(XLSX, data_only=True)
        rows = []
        for sn in SHEETS:
            rows.extend(parse_movement_rows(wb[sn]))

        # Sort by date — within a date, Excel order is preserved (stable sort)
        rows.sort(key=lambda r: r["date"])

        for r in rows:
            db.add(CreditLedgerEntry(
                id          = uuid.uuid4(),
                credit_id   = apple.id,
                date        = r["date"],
                time        = r["time"],
                description = r["description"],
                palod       = r["palod"],
                than        = r["than"],
                bayad       = r["bayad"],
                balance     = r["balance"],
                created_by  = "admin",
            ))

        db.commit()

        total_palod = sum(r["palod"] for r in rows)
        total_than  = sum(r["than"]  for r in rows)
        total_bayad = sum(r["bayad"] for r in rows)
        print(f"Seeded {len(rows)} ledger rows for Apple")
        print(f"  PALOD  ₱{total_palod:>14,.2f}")
        print(f"  THAN   ₱{total_than:>14,.2f}")
        print(f"  BAYAD  ₱{total_bayad:>14,.2f}")
        print(f"  Net    ₱{total_palod + total_than - total_bayad:>14,.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
