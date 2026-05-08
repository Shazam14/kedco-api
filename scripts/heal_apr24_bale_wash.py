"""
One-off heal for April 24 bale wash: Eunice borrowed ₱1,000,000 from the PHP
vault in the morning and returned it the same afternoon. Both legs were
recorded honestly, but the daily report shows BALE +1,795,000 / RETURNS
-1,000,000 — gross numbers that wash to the correct net (+795,000) but read
loud and confusing on the report card.

Strategy:
  • Snapshot the three wash rows (cash_replenishment + paired -1M
    REPLENISH_DRAWER safe_movement + the +1M MANUAL_DEPOSIT return).
  • Delete them in a single transaction.
  • Save full row state to scripts/audit/apr24_bale_wash_cleanup_<ts>.json
    so the original ledger is preserved and reversible.

Usage:
    .venv/bin/python -m scripts.heal_apr24_bale_wash --dry-run
    .venv/bin/python -m scripts.heal_apr24_bale_wash --apply
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.models.shift import CashReplenishment, SafeMovement


REPLENISH_ID  = "addfbdc8-8d64-41cb-905c-a7e608d4504a"  # 1M bale row
SM_DRAWER_ID  = "c082d533-6a78-4735-934b-e5abeae3e667"  # -1M REPLENISH_DRAWER
SM_RETURN_ID  = "16e80958-7c1a-4668-b919-11126eb8f66e"  # +1M MANUAL_DEPOSIT

AUDIT_DIR = Path(__file__).resolve().parent / "audit"


def _snap_replen(r: CashReplenishment) -> dict:
    return {
        "id":         str(r.id),
        "shift_id":   str(r.shift_id),
        "amount_php": r.amount_php,
        "source":     r.source,
        "note":       r.note,
        "added_at":   r.added_at.isoformat() if r.added_at else None,
    }


def _snap_movement(m: SafeMovement) -> dict:
    return {
        "id":                       str(m.id),
        "amount_php":               m.amount_php,
        "reason":                   m.reason,
        "note":                     m.note,
        "actor_username":           m.actor_username,
        "related_replenishment_id": str(m.related_replenishment_id) if m.related_replenishment_id else None,
        "related_dispatch_id":      str(m.related_dispatch_id)      if m.related_dispatch_id      else None,
        "movement_date":            m.movement_date.isoformat() if m.movement_date else None,
        "created_at":               m.created_at.isoformat()    if m.created_at    else None,
    }


def heal(apply: bool) -> int:
    db = SessionLocal()
    try:
        replen = db.query(CashReplenishment).filter(CashReplenishment.id == REPLENISH_ID).first()
        sm_drawer = db.query(SafeMovement).filter(SafeMovement.id == SM_DRAWER_ID).first()
        sm_return = db.query(SafeMovement).filter(SafeMovement.id == SM_RETURN_ID).first()

        problems = []
        if replen is None:    problems.append(f"  MISSING: cash_replenishment {REPLENISH_ID}")
        if sm_drawer is None: problems.append(f"  MISSING: safe_movement {SM_DRAWER_ID}")
        if sm_return is None: problems.append(f"  MISSING: safe_movement {SM_RETURN_ID}")
        if problems:
            print("!! Problems found — aborting:")
            for p in problems: print(p)
            return 1

        if replen.amount_php != 1_000_000.0:
            print(f"!! Unexpected amount on replen: {replen.amount_php}, expected 1,000,000 — aborting")
            return 1
        if sm_drawer.amount_php != -1_000_000.0 or sm_drawer.reason != "REPLENISH_DRAWER":
            print(f"!! Unexpected drawer movement: {sm_drawer.amount_php}/{sm_drawer.reason} — aborting")
            return 1
        if sm_return.amount_php != 1_000_000.0 or sm_return.reason != "MANUAL_DEPOSIT":
            print(f"!! Unexpected return movement: {sm_return.amount_php}/{sm_return.reason} — aborting")
            return 1

        snapshot = {
            "cash_replenishment": _snap_replen(replen),
            "safe_movement_drawer": _snap_movement(sm_drawer),
            "safe_movement_return": _snap_movement(sm_return),
        }

        print("Will delete:")
        print(f"  cash_replenishment {replen.id}  ₱{replen.amount_php:>12,.2f}  ({replen.source})  '{replen.note}'")
        print(f"  safe_movement      {sm_drawer.id}  ₱{sm_drawer.amount_php:>12,.2f}  ({sm_drawer.reason})  '{sm_drawer.note}'")
        print(f"  safe_movement      {sm_return.id}  ₱{sm_return.amount_php:>12,.2f}  ({sm_return.reason})  '{sm_return.note}'")

        if apply:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            audit_path = AUDIT_DIR / f"apr24_bale_wash_cleanup_{ts}.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            log = {
                "applied_at":  datetime.utcnow().isoformat() + "Z",
                "target_date": "2026-04-24",
                "reason":      ("Eunice borrowed ₱1M from PHP vault in the morning and returned it "
                                "the same afternoon. Both legs were recorded but display loudly on "
                                "the daily report (BALE +1.795M / RETURNS -1M). Removing the wash "
                                "pair so report shows true net bale (+₱795,000) and zero returns. "
                                "Net peso position unchanged."),
                "snapshot":    snapshot,
            }
            audit_path.write_text(json.dumps(log, indent=2))

            db.delete(sm_drawer)
            db.delete(sm_return)
            db.delete(replen)
            db.commit()

            print(f"\n✓ Deleted 3 rows")
            print(f"✓ Audit log: {audit_path}")
        else:
            print("\n(dry-run) no changes applied.")
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
