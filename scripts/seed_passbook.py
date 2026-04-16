"""
Seed demo passbook entries across several banks.
Safe to re-run — skips if entries already exist.

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/seed_passbook.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
from datetime import date
from app.core.database import SessionLocal
from app.models.passbook import PassbookEntry
from app.models.bank import Bank

db = SessionLocal()

if db.query(PassbookEntry).count() > 0:
    print("Passbook entries already exist — skipping.")
    db.close()
    sys.exit(0)

def bank_id(code: str) -> int:
    b = db.query(Bank).filter_by(code=code).first()
    if not b:
        raise ValueError(f"Bank '{code}' not found. Run seed_banks.py first.")
    return b.id

ENTRIES = [
    # (bank_code, amount, deposited_date, logged_by, notes)
    ("BDO",   150_000, date(2026, 4,  1), "cashier1", "Opening deposit — new passbook"),
    ("BDO",    75_000, date(2026, 4,  3), "cashier2", "Daily collection"),
    ("BDO",    90_000, date(2026, 4,  7), "cashier1", "Weekly remittance"),
    ("BDO",    60_000, date(2026, 4, 10), "cashier3", None),
    ("BDO",   110_000, date(2026, 4, 14), "cashier2", "Large USD sale proceeds"),
    ("BDO",    45_000, date(2026, 4, 16), "cashier1", "Today deposit"),

    ("BPI",   200_000, date(2026, 4,  2), "cashier1", "BPI account opening"),
    ("BPI",    80_000, date(2026, 4,  8), "cashier2", None),
    ("BPI",    55_000, date(2026, 4, 15), "cashier3", "JPY sale proceeds"),

    ("GCASH",  30_000, date(2026, 4,  5), "cashier1", "GCash settlement"),
    ("GCASH",  22_500, date(2026, 4, 11), "cashier2", "GCash settlement"),
    ("GCASH",  18_000, date(2026, 4, 16), "cashier1", "GCash settlement"),

    ("MAYA",   25_000, date(2026, 4,  9), "cashier2", "Maya collection"),
    ("MAYA",   17_500, date(2026, 4, 15), "cashier3", None),
]

added = 0
for code, amount, dep_date, logged_by, notes in ENTRIES:
    try:
        bid = bank_id(code)
    except ValueError as e:
        print(f"  SKIP: {e}")
        continue

    entry = PassbookEntry(
        id=uuid.uuid4(),
        bank_id=bid,
        amount=amount,
        deposited_date=dep_date,
        logged_by=logged_by,
        notes=notes,
    )
    db.add(entry)
    added += 1

db.commit()
db.close()
print(f"Seeded {added} passbook entries across BDO / BPI / GCash / Maya.")
