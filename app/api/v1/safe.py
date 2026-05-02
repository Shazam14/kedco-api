from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.today import get_today
from app.models.shift import SafeMovement
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/safe", tags=["safe"])

ALLOWED_REASONS = {
    "REPLENISH_DRAWER",
    "TOPUP_RIDER",
    "DISPATCH_RIDER",
    "DEPOSIT_FROM_SHIFT",
    "MANUAL_DEPOSIT",
    "MANUAL_WITHDRAWAL",
    "OTHER",
}


class SafeMovementIn(BaseModel):
    amount_php: float        # signed: + deposit, - withdrawal
    reason: str
    note: Optional[str] = None


class SafeMovementOut(BaseModel):
    id: str
    amount_php: float
    reason: str
    note: Optional[str] = None
    actor_username: str
    related_replenishment_id: Optional[str] = None
    related_dispatch_id: Optional[str] = None
    movement_date: date_type
    created_at: datetime


def _to_out(m: SafeMovement) -> SafeMovementOut:
    return SafeMovementOut(
        id=str(m.id),
        amount_php=m.amount_php,
        reason=m.reason,
        note=m.note,
        actor_username=m.actor_username,
        related_replenishment_id=str(m.related_replenishment_id) if m.related_replenishment_id else None,
        related_dispatch_id=str(m.related_dispatch_id) if m.related_dispatch_id else None,
        movement_date=m.movement_date,
        created_at=m.created_at,
    )


@router.get("")
async def get_safe(
    target_date: Optional[date_type] = Query(default=None, alias="date"),
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    target = target_date or get_today()

    todays = (
        db.query(SafeMovement)
        .filter(SafeMovement.movement_date == target)
        .order_by(SafeMovement.created_at)
        .all()
    )
    today_net = round(sum(m.amount_php for m in todays), 2)

    all_movements = db.query(SafeMovement).all()
    running_net = round(sum(m.amount_php for m in all_movements), 2)

    return {
        "date":         str(target),
        "today_net":    today_net,
        "running_net":  running_net,
        "movements":    [_to_out(m).model_dump(mode="json") for m in todays],
    }


@router.post("/movements", status_code=status.HTTP_201_CREATED)
async def create_movement(
    body: SafeMovementIn,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    reason = body.reason.upper()
    if reason not in ALLOWED_REASONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid reason: {reason}")
    if body.amount_php == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount cannot be zero.")

    movement = SafeMovement(
        amount_php=body.amount_php,
        reason=reason,
        note=body.note,
        actor_username=current_user.username,
        movement_date=get_today(),
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)

    return _to_out(movement).model_dump(mode="json")
