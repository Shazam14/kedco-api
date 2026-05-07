from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import date

from app.api.v1.auth import require_role, get_current_user, TokenData
from app.core.today import get_today, get_mock_date, set_mock_date, clear_mock_date

router = APIRouter(prefix="/config", tags=["config"])


class TestDateIn(BaseModel):
    date: date


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
):
    set_mock_date(body.date)
    return {"test_date": body.date.isoformat(), "message": f"Test date set to {body.date}"}


@router.delete("/test-date")
async def delete_test_date(
    current_user: TokenData = Depends(require_role("admin")),
):
    clear_mock_date()
    return {"message": "Test date cleared — system is back to real date"}
