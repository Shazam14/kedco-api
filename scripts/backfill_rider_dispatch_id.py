"""Backfill transactions.dispatch_id for all historical RIDER source txns.

Match strategy per (rider_username, date):
  - For each RIDER txn, find the dispatch whose
    [dispatch_time, return_time or +∞) window contains the txn's time.
  - If multiple match (overlap), pick the one with the latest dispatch_time
    that is still <= txn.time.
  - If none match (txn before any dispatch_time), assign to the earliest
    dispatch on that date — defensive fallback for clock-skew edge cases.
  - If no dispatch exists for that rider+date, leave dispatch_id NULL and log.

Idempotent: re-running skips txns that already have dispatch_id set.

Usage:
    /root/projects/api/.venv/bin/python /root/projects/api/scripts/backfill_rider_dispatch_id.py [--dry-run]
"""
import sys
from datetime import datetime, time as dtime
from collections import defaultdict
from sqlalchemy.orm import Session

# Make `app` importable when run as a script.
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.transaction import Transaction, RiderDispatch, TxnSource


def parse_time_str(s):
    """Parse '04:57 AM' style time string into a datetime.time."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%I:%M %p").time()
    except ValueError:
        return None


def main(dry_run: bool):
    db: Session = SessionLocal()
    try:
        rider_txns = (
            db.query(Transaction)
              .filter(Transaction.source == TxnSource.RIDER)
              .filter(Transaction.dispatch_id.is_(None))
              .order_by(Transaction.date, Transaction.cashier, Transaction.time)
              .all()
        )
        print(f"Candidates: {len(rider_txns)} RIDER txns with NULL dispatch_id")

        # Index dispatches by (rider, date) for quick lookup.
        dispatches = defaultdict(list)
        for d in db.query(RiderDispatch).all():
            dispatches[(d.rider_username, d.date)].append(d)
        for key in dispatches:
            dispatches[key].sort(key=lambda d: parse_time_str(d.dispatch_time) or dtime.min)

        matched = 0
        orphans = 0
        orphan_keys = set()
        for t in rider_txns:
            key = (t.cashier, t.date)
            day_dispatches = dispatches.get(key, [])
            if not day_dispatches:
                orphans += 1
                orphan_keys.add(key)
                continue

            txn_t = parse_time_str(t.time)
            if txn_t is None:
                # Unparseable time → assign to first dispatch of the day.
                target = day_dispatches[0]
            else:
                # Pick latest dispatch with dispatch_time <= txn_t. If none,
                # fall back to earliest dispatch on that date.
                candidates = [
                    d for d in day_dispatches
                    if (parse_time_str(d.dispatch_time) or dtime.min) <= txn_t
                ]
                target = candidates[-1] if candidates else day_dispatches[0]

            if not dry_run:
                t.dispatch_id = target.id
            matched += 1

        if dry_run:
            print(f"DRY RUN — would match {matched}, orphan {orphans}")
        else:
            db.commit()
            print(f"Matched + committed: {matched}")
            print(f"Orphans (no dispatch on that day): {orphans}")
        if orphan_keys:
            print("Orphan rider+date pairs:")
            for rider, date in sorted(orphan_keys):
                print(f"  {rider}  {date}")
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry)
