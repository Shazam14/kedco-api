from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from app.core.database import get_db
from app.models.audit import AuditLog
from app.api.v1.auth import require_role

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/log")
async def get_audit_log(
    table:  Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user:   Optional[str] = Query(None),
    limit:  int           = Query(200, le=500),
    current_user=Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.changed_at.desc())
    if table:  q = q.filter(AuditLog.table_name == table)
    if action: q = q.filter(AuditLog.action == action.upper())
    if user:   q = q.filter(AuditLog.changed_by.ilike(f"%{user}%"))
    rows = q.limit(limit).all()
    return [
        {
            "id":         str(r.id),
            "table":      r.table_name,
            "record_id":  r.record_id,
            "action":     r.action,
            "changed_by": r.changed_by,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            "old_value":  r.old_value,
            "new_value":  r.new_value,
            "note":       r.note,
        }
        for r in rows
    ]
