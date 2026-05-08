"""
Heal v3 for April 24, 2026 — backfills the missing 900k dispatch from Ken's
handwritten reconciliation (excel_files/gemini-code-1778205400100.txt).

Ken's OUT column shows 8 line items summing to ₱3,878,743.60.
The DB has 5 dispatches summing to ₱2,979,013.60 (rider07's cash_php already
folds in his 200k + 63,413 topups). One ₱900,000 dispatch is on Ken's paper
but never entered. After backfill, system closing reconciles to Ken's
₱3,106,113.40 exactly.

Rider attribution: best guess is rider02. He has no 4/24 row in the DB and
his 4/23 dispatch was ₱700k (similar volume). Marked PAPER_ONLY so the entry
is visibly different from live-system rows.

Strategy:
  • Insert one RiderDispatch with cash_php=900000, remit_php=0,
    status=RETURNED, dispatched_by=treasurer1, notes prefixed PAPER_ONLY.
  • Audit JSON in scripts/audit/.

Usage:
    .venv/bin/python -m scripts.heal_apr24_v3_missing_dispatch --dry-run
    .venv/bin/python -m scripts.heal_apr24_v3_missing_dispatch --apply
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, date as date_type
from pathlib import Path

from app.core.database import SessionLocal
from app.models.transaction import RiderDispatch, DispatchStatus

EXPECTED_DATE = date_type(2026, 4, 24)

INSERT_DISPATCH = {
    "date":           EXPECTED_DATE,
    "rider_username": "rider02",
    "rider_name":     "Rider 02",
    "cash_php":       900_000.0,
    "remit_php":      0.0,
    "status":         DispatchStatus.RETURNED,
    "dispatched_by":  "treasurer1",
    "notes":          "PAPER_ONLY — Ken's 4/24 book reconciliation 2026-05-08; "
                      "₱900k OUT line never entered live; rider attribution best-guess",
    "dispatch_time":  "10:00",
    "return_time":    "15:00",
    "created_at":     datetime.fromisoformat("2026-04-24T10:00:00+00:00"),
    "updated_at":     datetime.fromisoformat("2026-04-24T15:00:00+00:00"),
}

AUDIT_PATH = Path(__file__).resolve().parent / "audit" / (
    "apr24_v3_missing_dispatch_"
    + datetime.now().strftime("%Y%m%d_%H%M%S")
    + ".json"
)


def heal(apply: bool) -> int:
    db = SessionLocal()
    try:
        new_id = str(uuid.uuid4())
        print(f"  INSERT: RiderDispatch {new_id} rider02 cash_php=900000 remit=0 PAPER_ONLY")
        if apply:
            db.add(RiderDispatch(id=new_id, **INSERT_DISPATCH))

        log = {
            "applied_at":  datetime.now().isoformat() + "Z",
            "target_date": EXPECTED_DATE.isoformat(),
            "reason":      (
                "Backfill missing 900k OUT line from Ken's 4/24 handwritten reconciliation. "
                "Closes the system-vs-book gap; entry is tagged PAPER_ONLY in notes for audit."
            ),
            "actions": {
                "insert_dispatch_900k": {
                    "id":     new_id,
                    "row":    {
                        **INSERT_DISPATCH,
                        "date": INSERT_DISPATCH["date"].isoformat(),
                        "status": INSERT_DISPATCH["status"].value,
                        "created_at": INSERT_DISPATCH["created_at"].isoformat(),
                        "updated_at": INSERT_DISPATCH["updated_at"].isoformat(),
                    },
                    "status": "applied" if apply else "would_apply",
                },
            },
        }

        if apply:
            AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
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
