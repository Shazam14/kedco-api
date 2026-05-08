"""
Heal v2 for April 24, 2026 — corrects yesterday's over-cleanup and adds
the missing inter-branch row.

Yesterday's heal (apr24_bale_wash_cleanup_20260508_012215.json) deleted three
rows on the assumption that the 1M Eunice borrow + 1M return were a wash. Ken
later produced his handwritten reconciliation showing the 1M return-to-vault
is a separate legit treasurer action — not the counterpart to her borrow.
The 1M vault deposit must be restored.

Ken's full formula for 4/24 also includes:
    + FROM CTS  ₱200,000  (inter-branch cash transfer in)

That row never existed in the DB. We model it as a cash_replenishment with
source='INTER_BRANCH' so it lands in the treasurer's drawer like BALE does
(source='SAFE'), but doesn't touch the vault.

Net effect after this heal:
  bale       795,000     (unchanged)
  inter      200,000     (NEW)
  vault ret  1,000,000   (RESTORED)

  3,106,113.40 = 2,631,549 + 4,358,308 - 3,878,743.60 + 795,000 + 200,000 - 1,000,000

Usage:
    .venv/bin/python -m scripts.heal_apr24_v2_returns_and_inter_branch --dry-run
    .venv/bin/python -m scripts.heal_apr24_v2_returns_and_inter_branch --apply
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, date as date_type
from pathlib import Path

from app.core.database import SessionLocal
from app.models.shift import SafeMovement, CashReplenishment

EXPECTED_DATE = date_type(2026, 4, 24)
TREASURER_SHIFT_ID = "ef387bf1-b69c-4920-9c75-1ac9c108fa49"
TREASURER_USERNAME = "treasurer1"

# Restore the 1M MANUAL_DEPOSIT we wrongly deleted yesterday.
RESTORE_MANUAL_DEPOSIT = {
    "id":             "16e80958-7c1a-4668-b919-11126eb8f66e",
    "amount_php":     1_000_000.0,
    "reason":         "MANUAL_DEPOSIT",
    "note":           "ULI 4/24 — 1M returned to PHP vault (restored 2026-05-08)",
    "actor_username": TREASURER_USERNAME,
    "movement_date":  EXPECTED_DATE,
    "created_at":     datetime.fromisoformat("2026-04-24T14:00:00+00:00"),
}

# New row: 200k inter-branch cash in from CTS.
INSERT_INTER_BRANCH = {
    "shift_id":   TREASURER_SHIFT_ID,
    "amount_php": 200_000.0,
    "source":     "INTER_BRANCH",
    "note":       "from CTS — Ken's 4/24 reconciliation",
    "added_at":   datetime.fromisoformat("2026-04-24T08:00:00+00:00"),
}

AUDIT_PATH = Path(__file__).resolve().parent / "audit" / (
    "apr24_v2_returns_and_inter_branch_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".json"
)


def heal(apply: bool) -> int:
    db = SessionLocal()
    try:
        # 1. Restore the 1M MANUAL_DEPOSIT row.
        existing = db.query(SafeMovement).filter(
            SafeMovement.id == RESTORE_MANUAL_DEPOSIT["id"]
        ).first()
        if existing is not None:
            print(f"  SKIP: SafeMovement {RESTORE_MANUAL_DEPOSIT['id']} already exists.")
            restore_action = "skipped"
        else:
            print(f"  RESTORE: SafeMovement {RESTORE_MANUAL_DEPOSIT['id']} +₱1,000,000 MANUAL_DEPOSIT")
            restore_action = "applied" if apply else "would_apply"
            if apply:
                db.add(SafeMovement(**RESTORE_MANUAL_DEPOSIT))

        # 2. Insert the FROM CTS row.
        new_repl_id = str(uuid.uuid4())
        print(f"  INSERT: CashReplenishment {new_repl_id} +₱200,000 source=INTER_BRANCH (FROM CTS)")
        if apply:
            db.add(CashReplenishment(id=new_repl_id, **INSERT_INTER_BRANCH))

        log = {
            "applied_at":  datetime.now().isoformat() + "Z",
            "target_date": EXPECTED_DATE.isoformat(),
            "reason":      (
                "Restore wrongly-deleted 1M MANUAL_DEPOSIT (Ken's reconciliation shows it "
                "is a real return-to-vault, not a wash with Eunice's borrow). Add 200k "
                "INTER_BRANCH from CTS that was never recorded digitally."
            ),
            "actions": {
                "restore_safe_movement_1m": {
                    "row":    RESTORE_MANUAL_DEPOSIT,
                    "status": restore_action,
                },
                "insert_inter_branch_200k": {
                    "id":     new_repl_id,
                    "row":    {**INSERT_INTER_BRANCH, "added_at": INSERT_INTER_BRANCH["added_at"].isoformat()},
                    "status": "applied" if apply else "would_apply",
                },
            },
        }

        if apply:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            # serialize datetime in restore row
            log_serialized = json.loads(json.dumps(log, default=str))
            AUDIT_PATH.write_text(json.dumps(log_serialized, indent=2))
            db.commit()
            print(f"\n✓ Applied")
            print(f"✓ Audit log: {AUDIT_PATH}")
        else:
            print(f"\n(dry-run) — no changes committed")
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
