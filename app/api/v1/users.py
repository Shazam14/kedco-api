from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/users", tags=["users"])


class UserUpdateIn(BaseModel):
    full_name: Optional[str] = None
    branch:    Optional[str] = None
    is_active: Optional[bool] = None


class PasswordResetIn(BaseModel):
    new_password: str


def _user_out(u: User) -> dict:
    return {
        "id":        str(u.id),
        "username":  u.username,
        "full_name": u.full_name,
        "role":      u.role.value,
        "branch":    u.branch,
        "is_active": u.is_active,
    }


@router.get("/")
async def list_users(
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """List all users grouped by role."""
    users = db.query(User).order_by(User.role, User.username).all()
    return [_user_out(u) for u in users]


@router.patch("/{username}")
async def update_user(
    username: str,
    payload: UserUpdateIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Update a user's display name, branch, or active status."""
    user = db.query(User).filter_by(username=username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.branch is not None:
        user.branch = payload.branch
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    return _user_out(user)


@router.post("/{username}/reset-password")
async def reset_password(
    username: str,
    payload: PasswordResetIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Reset a user's password (admin only)."""
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters.",
        )
    user = db.query(User).filter_by(username=username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": f"Password reset for '{username}'."}
