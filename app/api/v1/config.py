from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.v1.auth import require_role, get_current_user, TokenData
from app.core.database import get_db
from app.core.today import get_today, get_mock_date, set_mock_date, clear_mock_date
from app.models.currency import DailyRate, DailyPosition

router = APIRouter(prefix="/config", tags=["config"])


class TestDateIn(BaseModel):
    date: date


def _copy_forward_setup(db: Session, target: date, actor: str) -> dict:
    """
    Ensure target date has daily_rates and daily_positions rows.
    If target is empty for either table, copy from the most recent strictly
    earlier date that does have rows. Idempotent: skips when target already
    has data. Returns counts + source dates so the UI can mention what happened.
    """
    out: dict = {
        "rates_copied": 0,
        "positions_copied": 0,
        "rates_source": None,
        "positions_source": None,
    }

    if db.query(DailyRate).filter_by(date=target).count() == 0:
        src = db.query(func.max(DailyRate.date)).filter(DailyRate.date < target).scalar()
        if src is not None:
            for r in db.query(DailyRate).filter_by(date=src).all():
                db.add(DailyRate(
                    date          = target,
                    currency_code = r.currency_code,
                    buy_rate      = r.buy_rate,
                    sell_rate     = r.sell_rate,
                    set_by        = f"auto-copy:{actor}",
                ))
                out["rates_copied"] += 1
            out["rates_source"] = src.isoformat()

    if db.query(DailyPosition).filter_by(date=target).count() == 0:
        src = db.query(func.max(DailyPosition.date)).filter(DailyPosition.date < target).scalar()
        if src is not None:
            for p in db.query(DailyPosition).filter_by(date=src).all():
                db.add(DailyPosition(
                    date          = target,
                    currency_code = p.currency_code,
                    carry_in_qty  = p.carry_in_qty,
                    carry_in_rate = p.carry_in_rate,
                ))
                out["positions_copied"] += 1
            out["positions_source"] = src.isoformat()

    if out["rates_copied"] or out["positions_copied"]:
        db.commit()
    return out


@router.get("/today")
async def get_today_endpoint(
    current_user: TokenData = Depends(get_current_user),
):
    return {"today": get_today().isoformat()}


@router.get("/test-date")
async def get_test_date(
    current_user: TokenData = Depends(require_role("admin")),
):
    d = get_mock_date()
    return {"test_date": d.isoformat() if d else None}


@router.post("/test-date")
async def set_test_date(
    body: TestDateIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    set_mock_date(body.date)
    copied = _copy_forward_setup(db, body.date, current_user.username)
    return {
        "test_date": body.date.isoformat(),
        "message": f"Test date set to {body.date}",
        **copied,
    }


@router.delete("/test-date")
async def delete_test_date(
    current_user: TokenData = Depends(require_role("admin")),
):
    clear_mock_date()
    return {"message": "Test date cleared — system is back to real date"}
