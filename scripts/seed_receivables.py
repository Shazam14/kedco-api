"""
Seed pending_receivables from excel_files/cheque.txt.

Idempotent: skips rows where an entry already exists with the same
(customer_name, amount_php, bank_account). Run once after migration.

Faith → NEEDS_REVIEW (marked "no payment" on the source).
Other entries default to PENDING.
"""
from __future__ import annotations

import uuid
from datetime import date as DateType
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.receivable import PendingReceivable


# (customer, amount, method, bank, date_iso_or_None, status, note)
ENTRIES: list[tuple[str, float, str, str, str | None, str, str | None]] = [
    # ── Sir Ed / GPO  (₱604,651) ───────────────────────────────────────
    ("pnb",          100_000.00, "PNB",      "GPO", "2026-04-17", "PENDING", None),
    ("Cus che",      106_500.00, "CHEQUE",   "GPO", None,         "PENDING", "sub-entry: 116,500 4/11"),
    ("Ann",           21_500.00, "PNB",      "GPO", "2026-04-29", "PENDING", None),
    ("Sgd",           54_805.00, "UNKNOWN",  "GPO", "2026-04-29", "PENDING", None),
    ("Walk in",      113_605.00, "WALKIN",   "GPO", "2026-05-02", "PENDING", None),
    ("Matimco",        2_361.00, "GCASH",    "GPO", "2026-05-02", "PENDING", None),
    ("Kyna",          37_920.00, "GCASH",    "GPO", "2026-05-02", "PENDING", None),
    ("Tancor",        11_790.00, "GCASH",    "GPO", "2026-05-02", "PENDING", None),
    ("Kyna",           3_950.00, "GCASH",    "GPO", None,         "PENDING", None),
    ("Edward",        10_925.00, "PNB",      "GPO", None,         "PENDING", None),
    ("Jon",           11_385.00, "GCASH",    "GPO", None,         "PENDING", None),
    ("J.king",        24_200.00, "GCASH",    "GPO", None,         "PENDING", None),
    ("Delyn",         12_170.00, "UNKNOWN",  "GPO", "2026-05-11", "PENDING", None),
    ("Rhena",         34_840.00, "UNKNOWN",  "GPO", "2026-05-13", "PENDING", None),
    ("Mandani",        5_200.00, "GCASH",    "GPO", "2026-05-14", "PENDING", None),
    ("Angie",         10_000.00, "GCASH",    "GPO", "2026-05-15", "PENDING", None),
    ("Jmall aud",     22_500.00, "GCASH",    "GPO", None,         "PENDING", None),
    ("Jaime",         21_000.00, "GCASH",    "GPO", "2026-05-17", "PENDING", None),

    # ── CBC ACCT  (₱1,110,689.80) ──────────────────────────────────────
    ("Ryan",          50_000.00, "CHEQUE",   "CBC", None,         "PENDING", None),
    ("Radison",       50_000.00, "CHEQUE",   "CBC", None,         "PENDING", None),
    ("Irikoy",        71_400.00, "UNKNOWN",  "CBC", "2026-01-14", "PENDING", None),
    ("J.Dale",        30_059.00, "UNKNOWN",  "CBC", "2026-04-17", "PENDING", None),
    ("W-in",          15_500.00, "UNKNOWN",  "CBC", "2026-05-06", "PENDING", None),
    ("Cheryl",        13_350.00, "UNKNOWN",  "CBC", None,         "PENDING", None),
    ("Jeoffrey",      27_400.00, "UNKNOWN",  "CBC", None,         "PENDING", None),
    ("Kenneth",       39_200.00, "CHEQUE",   "CBC", None,         "PENDING", None),
    ("Home builders", 22_500.00, "CHEQUE",   "CBC", None,         "PENDING", None),
    ("Faith",        145_050.00, "UNKNOWN",  "CBC", None,         "NEEDS_REVIEW", "no payment"),
    ("Gloria",        18_800.00, "UNKNOWN",  "CBC", None,         "PENDING", None),
    ("Cts",            2_725.00, "UNKNOWN",  "CBC", "2026-05-16", "PENDING", None),
    ("Senyor",        77_800.00, "UNKNOWN",  "CBC", "2026-05-18", "PENDING", None),
    ("Atlantic",     154_625.00, "UNKNOWN",  "CBC", "2026-05-18", "PENDING", None),
    ("Stefanie",      36_000.00, "UNKNOWN",  "CBC", "2026-05-18", "PENDING", None),
    ("Helen",        306_280.80, "UNKNOWN",  "CBC", "2026-05-18", "PENDING", None),
    ("Cts",           50_000.00, "UNKNOWN",  "CBC", None,         "PENDING", None),

    # ── MBTC PB  (₱538,104) ────────────────────────────────────────────
    ("Edward",         4_784.00, "UNKNOWN",  "MBTC", None,        "PENDING", None),
    ("Shore",         73_980.00, "UNKNOWN",  "MBTC", None,        "PENDING", None),
    ("Dexter",       123_000.00, "UNKNOWN",  "MBTC", None,        "PENDING", None),
    ("Helen",        311_600.00, "UNKNOWN",  "MBTC", None,        "PENDING", None),
    ("Shore",         24_740.00, "UNKNOWN",  "MBTC", None,        "PENDING", None),
]


def main() -> None:
    db: Session = SessionLocal()
    inserted = skipped = 0
    try:
        for name, amount, method, bank, date_iso, status, note in ENTRIES:
            dupe = (
                db.query(PendingReceivable)
                .filter(
                    PendingReceivable.customer_name == name,
                    PendingReceivable.amount_php == amount,
                    PendingReceivable.bank_account == bank,
                )
                .first()
            )
            if dupe:
                skipped += 1
                continue
            entry_date = DateType.fromisoformat(date_iso) if date_iso else None
            db.add(PendingReceivable(
                id=uuid.uuid4(),
                customer_name=name,
                amount_php=round(amount, 2),
                method=method,
                bank_account=bank,
                entry_date=entry_date,
                status=status,
                note=note,
                created_by="seed_cheque_txt",
            ))
            inserted += 1
        db.commit()
        print(f"Inserted: {inserted}   Skipped (already present): {skipped}")

        # Quick totals per bank to verify against source.
        from sqlalchemy import func
        for bank in ("GPO", "CBC", "MBTC"):
            total = (
                db.query(func.coalesce(func.sum(PendingReceivable.amount_php), 0.0))
                .filter(PendingReceivable.bank_account == bank)
                .scalar()
            )
            print(f"  {bank}: ₱{total:,.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
