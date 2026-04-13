"""
Reset today's data — clears rates, positions, and transactions for today.
Safe to re-run. Does NOT touch other dates.

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/reset_today.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from app.core.database import SessionLocal
from app.models.currency import DailyRate, DailyPosition
from app.models.transaction import Transaction, DailySummary

TODAY = date.today()

def main():
    print(f"Resetting all data for {TODAY}...")
    db = SessionLocal()
    try:
        txns      = db.query(Transaction).filter_by(date=TODAY).delete()
        rates     = db.query(DailyRate).filter_by(date=TODAY).delete()
        positions = db.query(DailyPosition).filter_by(date=TODAY).delete()
        summary   = db.query(DailySummary).filter_by(date=TODAY).delete()
        db.commit()
        print(f"  Transactions deleted : {txns}")
        print(f"  Rates deleted        : {rates}")
        print(f"  Positions deleted    : {positions}")
        print(f"  EOD summary deleted  : {summary}")
        print(f"\nDone. Today is now a clean slate.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
