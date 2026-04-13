"""
Seed today's test data — rates + transactions + positions.
Safe to re-run (skips existing records).

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/seed_today.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime
from app.core.database import SessionLocal
from app.models.currency import DailyRate, DailyPosition
from app.models.transaction import Transaction, TxnType, TxnSource

TODAY = date.today()

# ── Today's rates (realistic Cebu rates) ─────────────────────────────────────
RATES = [
    # code,   buy,      sell
    ("USD",   57.20,    57.80),
    ("JPY",   0.3810,   0.3890),
    ("KRW",   0.0410,   0.0430),
    ("EUR",   63.50,    64.20),
    ("GBP",   74.80,    75.60),
    ("SGD",   42.80,    43.40),
    ("AUD",   36.50,    37.10),
    ("HKD",    7.28,     7.42),
    ("CNY",    7.85,     8.05),
    ("MYR",   12.40,    12.80),
    ("NZD",   33.80,    34.50),
    ("TWD",    1.75,     1.82),
    ("THB",    1.58,     1.65),
    ("SAR",   15.20,    15.60),
    ("AED",   15.50,    15.90),
    ("QAR",   15.60,    16.00),
    ("KWD",  185.00,   190.00),
    ("BHD",  151.00,   156.00),
    ("OMR",  148.00,   153.00),
    ("CHF",   63.00,    64.00),
    ("CAD",   41.50,    42.20),
    ("SEK",    5.40,     5.60),
    ("NOK",    5.20,     5.40),
    ("DKK",    8.50,     8.75),
    ("IDR",   0.0035,   0.0037),
    ("VND",   0.0022,   0.0024),
    ("BND",   42.80,    43.40),
    ("INR",    0.680,    0.710),
    ("JOD",   80.50,    82.50),
]

# ── Opening positions (carry-in from yesterday) ───────────────────────────────
POSITIONS = [
    ("USD", 2500,  57.50),
    ("JPY", 80000, 0.3880),
    ("KRW", 50000, 0.0425),
    ("EUR", 800,   63.90),
    ("GBP", 500,   75.20),
    ("SGD", 1200,  43.10),
    ("AUD", 900,   36.80),
    ("HKD", 3000,   7.35),
    ("CNY", 2000,   7.95),
    ("SAR", 1500,  15.40),
    ("AED", 1500,  15.70),
]

# ── Test transactions ─────────────────────────────────────────────────────────
TRANSACTIONS = [
    # id,             time,    type,  source,  ccy,   qty,    rate,   avg,    cashier,      customer
    ("OR-00010413", "08:32", "BUY",  "COUNTER", "USD", 500,  57.20, 57.20, "cashier1", "Walk-in"),
    ("OR-00020413", "08:55", "SELL", "COUNTER", "USD", 300,  57.80, 57.38, "cashier1", "Maria Santos"),
    ("OR-00030413", "09:10", "BUY",  "COUNTER", "JPY", 20000, 0.381, 0.381, "cashier1", "Walk-in"),
    ("OR-00040413", "09:45", "SELL", "COUNTER", "EUR", 200,  64.20, 63.90, "cashier2", "John Reyes"),
    ("OR-00050413", "10:15", "BUY",  "COUNTER", "KRW", 100000, 0.041, 0.041, "cashier2", "Walk-in"),
    ("OR-00060413", "10:40", "SELL", "COUNTER", "USD", 500,  57.80, 57.38, "cashier1", "Ana Cruz"),
    ("OR-00070413", "11:05", "BUY",  "COUNTER", "SGD", 300,  42.80, 42.80, "cashier2", "Walk-in"),
    ("OR-00080413", "11:30", "SELL", "COUNTER", "JPY", 10000, 0.389, 0.381, "cashier1", "Walk-in"),
    ("RD-00010413", "09:30", "BUY",  "RIDER",   "USD", 800,  57.20, 57.20, "rider01",  "Rider Client A"),
    ("RD-00020413", "10:00", "SELL", "RIDER",   "USD", 600,  57.80, 57.29, "rider01",  "Rider Client B"),
]


def seed_rates(db):
    inserted = skipped = 0
    for code, buy, sell in RATES:
        exists = db.query(DailyRate).filter_by(date=TODAY, currency_code=code).first()
        if exists:
            skipped += 1
            continue
        db.add(DailyRate(date=TODAY, currency_code=code, buy_rate=buy, sell_rate=sell, set_by="admin"))
        inserted += 1
    db.commit()
    print(f"  Rates     — inserted: {inserted}, skipped: {skipped}")


def seed_positions(db):
    inserted = skipped = 0
    for code, qty, rate in POSITIONS:
        exists = db.query(DailyPosition).filter_by(date=TODAY, currency_code=code).first()
        if exists:
            skipped += 1
            continue
        db.add(DailyPosition(date=TODAY, currency_code=code, carry_in_qty=qty, carry_in_rate=rate))
        inserted += 1
    db.commit()
    print(f"  Positions — inserted: {inserted}, skipped: {skipped}")


def seed_transactions(db):
    inserted = skipped = 0
    for txn_id, time, typ, source, ccy, qty, rate, avg, cashier, customer in TRANSACTIONS:
        if db.query(Transaction).filter_by(id=txn_id).first():
            skipped += 1
            continue
        php_amt = qty * rate
        than    = (rate - avg) * qty if typ == "SELL" else 0.0
        db.add(Transaction(
            id           = txn_id,
            date         = TODAY,
            time         = time,
            type         = TxnType[typ],
            source       = TxnSource[source],
            currency_code= ccy,
            foreign_amt  = qty,
            rate         = rate,
            php_amt      = php_amt,
            daily_avg_cost = avg,
            than         = than,
            cashier      = cashier,
            customer     = customer,
        ))
        inserted += 1
    db.commit()
    print(f"  Transactions — inserted: {inserted}, skipped: {skipped}")


def main():
    print(f"Seeding test data for {TODAY}...")
    db = SessionLocal()
    try:
        seed_rates(db)
        seed_positions(db)
        seed_transactions(db)
        print("Done. Reload the dashboard to see data.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
