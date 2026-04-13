"""
Seed Ken's actual stock data from 3/31/26 as Day 1 opening positions.

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/seed_ken_csv.py [YYYY-MM-DD]

    Default date: 2026-03-31 (from Ken's CSV)
    Override:     .venv/bin/python scripts/seed_ken_csv.py 2026-04-13
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from app.core.database import SessionLocal
from app.models.currency import DailyPosition, Currency

# ── Ken's stocks from 3/31/26 CSV ────────────────────────────────────────────
# csv_code, db_code,  qty,          rate
KEN_STOCKS = [
    ("USD",  "USD",  26088,       60.80),
    ("JPY",  "JPY",  571000,      0.3705),
    ("KRW",  "KRW",  1297000,     0.0403),
    ("AED",  "AED",  4610,        15.30),
    ("AUD",  "AUD",  2475,        41.07),
    ("CAD",  "CAD",  4590,        42.58),
    ("CHF",  "CHF",  2260,        74.58),
    ("CNY",  "CNY",  10697,       7.90),
    ("EUR",  "EUR",  10795,       68.96),
    ("GBP",  "GBP",  1315,        78.00),
    ("HKD",  "HKD",  8960,        7.25),
    ("MYR",  "MYR",  5496,        14.02),
    ("NTD",  "TWD",  130900,      1.79),   # NTD = TWD (New Taiwan Dollar)
    ("NZD",  "NZD",  4310,        33.17),
    ("QR",   "QAR",  58,          14.98),   # QR = QAR (Qatari Riyal)
    ("SAR",  "SAR",  1733,        15.19),
    ("SGD",  "SGD",  300,         46.53),
    ("THB",  "THB",  3290,        1.86),
    ("DKK",  "DKK",  550,         5.60),
    ("INR",  "INR",  72390,       0.45),
    ("MOP",  "MOP",  370,         6.34),    # Macanese Pataca
    ("NOK",  "NOK",  4600,        2.37),
    ("VND",  "VND",  172420000,   0.0026),
    # Zero qty — skipped: BHD, BND, IDR, OMR, TYR, KD
]


def main():
    target_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 3, 31)
    print(f"Seeding Ken's Day 1 opening positions for {target_date}...")

    db = SessionLocal()
    try:
        # Fetch valid currency codes from DB
        valid_codes = {c.code for c in db.query(Currency).all()}

        inserted = skipped_dup = skipped_no_db = skipped_zero = 0
        for csv_code, db_code, qty, rate in KEN_STOCKS:
            if db_code is None:
                print(f"  SKIP {csv_code} — not in currency master (no db_code mapped)")
                skipped_no_db += 1
                continue
            if db_code not in valid_codes:
                print(f"  SKIP {csv_code} ({db_code}) — not in currencies table")
                skipped_no_db += 1
                continue
            if qty == 0:
                skipped_zero += 1
                continue

            exists = db.query(DailyPosition).filter_by(date=target_date, currency_code=db_code).first()
            if exists:
                print(f"  SKIP {db_code} — already exists for {target_date}")
                skipped_dup += 1
                continue

            db.add(DailyPosition(
                date=target_date,
                currency_code=db_code,
                carry_in_qty=qty,
                carry_in_rate=rate,
            ))
            php_total = qty * rate
            print(f"  + {db_code:5s}  qty={qty:>15,.0f}  rate={rate:>10.4f}  PHP={php_total:>15,.2f}")
            inserted += 1

        db.commit()
        print(f"\nDone — inserted: {inserted}, skipped duplicates: {skipped_dup}, "
              f"skipped (no DB entry): {skipped_no_db}, skipped (zero qty): {skipped_zero}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
