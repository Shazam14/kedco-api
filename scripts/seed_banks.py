"""
Seed default banks and e-wallets.
Safe to re-run — skips existing codes.

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/seed_banks.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.models.bank import Bank

BANKS = [
    # (code, name, sort_order)
    # ── Major PH Banks ──────────────────────────────────────
    ("BDO",      "Banco de Oro (BDO)",            1),
    ("BPI",      "Bank of the Philippine Islands", 2),
    ("MBT",      "Metrobank",                      3),
    ("PNB",      "Philippine National Bank",       4),
    ("UBP",      "UnionBank",                      5),
    ("LBP",      "Landbank",                       6),
    ("RCBC",     "RCBC",                           7),
    ("CBC",      "Chinabank",                      8),
    ("SECB",     "Security Bank",                  9),
    ("EWB",      "EastWest Bank",                 10),
    ("PSB",      "PSBank",                        11),
    ("AUB",      "Asia United Bank (AUB)",        12),
    ("RB",       "Robinsons Bank",                13),
    ("DBP",      "Development Bank of the Philippines", 14),
    ("CIMB",     "CIMB Bank",                     15),
    ("MAYABANK", "Maya Bank",                     16),
    ("SB",       "Sterling Bank",                 17),
    # ── E-wallets ────────────────────────────────────────────
    ("GCASH",    "GCash",                         20),
    ("MAYA",     "Maya (PayMaya)",                21),
    ("SHOPEE",   "ShopeePay",                     22),
]

def main():
    db = SessionLocal()
    try:
        inserted = skipped = 0
        for code, name, sort_order in BANKS:
            if db.query(Bank).filter_by(code=code).first():
                skipped += 1
                continue
            db.add(Bank(code=code, name=name, sort_order=sort_order))
            print(f"  + {code:10s}  {name}")
            inserted += 1
        db.commit()
        print(f"\nDone — inserted: {inserted}, skipped: {skipped}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
