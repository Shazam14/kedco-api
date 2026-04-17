from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date as date_type, datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.models.credit import SpecialCredit, CreditInstallment, CreditDraw, AppSetting, CreditType, CreditStatus
from app.api.v1.auth import require_role, TokenData

PHT = timezone(timedelta(hours=8))

DEFAULT_SETTINGS = {
    "credit_draw_interval_minutes": "60",   # min minutes between draws per customer
    "credit_draw_max_per_day":      "24",   # max draws per credit per day
    "credit_draw_max_amount":       "0",    # 0 = unlimited
}

router = APIRouter(prefix="/credits", tags=["credits"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class InstallmentIn(BaseModel):
    due_date: date_type
    amount:   float


class CreditIn(BaseModel):
    customer_name:  str
    currency_code:  str
    principal:      float
    interest:       float
    credit_type:    CreditType          # UPFRONT or INSTALLMENT
    disbursed_date: date_type
    notes:          Optional[str] = None
    installments:   list[InstallmentIn] # always at least 1 (admin builds the list on the front-end)


class InstallmentOut(BaseModel):
    id:             str
    installment_no: int
    due_date:       date_type
    amount:         float
    paid_at:        Optional[date_type]
    received_by:    Optional[str]


class DrawOut(BaseModel):
    id:         str
    amount:     float
    notes:      Optional[str]
    created_by: str
    created_at: str


class CreditOut(BaseModel):
    id:             str
    customer_name:  str
    currency_code:  str
    principal:      float
    interest:       float
    credit_type:    str
    status:         str
    disbursed_date: date_type
    notes:          Optional[str]
    created_by:     str
    installments:   list[InstallmentOut]
    draws:          list[DrawOut] = []


class CreditDrawRules(BaseModel):
    interval_minutes: int
    max_per_day:      int
    max_amount:       float


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_out(credit: SpecialCredit, installments: list[CreditInstallment], draws: list[CreditDraw] | None = None) -> CreditOut:
    return CreditOut(
        id=str(credit.id),
        customer_name=credit.customer_name,
        currency_code=credit.currency_code,
        principal=credit.principal,
        interest=credit.interest,
        credit_type=credit.credit_type.value,
        status=credit.status.value,
        disbursed_date=credit.disbursed_date,
        notes=credit.notes,
        created_by=credit.created_by,
        installments=[
            InstallmentOut(
                id=str(i.id),
                installment_no=i.installment_no,
                due_date=i.due_date,
                amount=i.amount,
                paid_at=i.paid_at,
                received_by=i.received_by,
            )
            for i in sorted(installments, key=lambda x: x.installment_no)
        ],
        draws=[
            DrawOut(
                id=str(d.id),
                amount=d.amount,
                notes=d.notes,
                created_by=d.created_by,
                created_at=d.created_at.isoformat() if d.created_at else '',
            )
            for d in sorted(draws or [], key=lambda x: x.created_at or datetime.min)
        ],
    )


def _get_setting(db: Session, key: str) -> str:
    row = db.query(AppSetting).filter_by(key=key).first()
    return row.value if row else DEFAULT_SETTINGS[key]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=CreditOut, status_code=status.HTTP_201_CREATED)
async def create_credit(
    payload: CreditIn,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not payload.installments:
        raise HTTPException(status_code=400, detail="At least one installment is required.")

    credit = SpecialCredit(
        id=uuid.uuid4(),
        customer_name=payload.customer_name,
        currency_code=payload.currency_code.upper(),
        principal=payload.principal,
        interest=payload.interest,
        credit_type=payload.credit_type,
        status=CreditStatus.ACTIVE,
        disbursed_date=payload.disbursed_date,
        notes=payload.notes,
        created_by=current_user.username,
    )
    db.add(credit)
    db.flush()  # get the id before inserting installments

    installments = []
    for idx, slot in enumerate(payload.installments, start=1):
        inst = CreditInstallment(
            id=uuid.uuid4(),
            credit_id=credit.id,
            installment_no=idx,
            due_date=slot.due_date,
            amount=slot.amount,
        )
        db.add(inst)
        installments.append(inst)

    db.commit()
    return _build_out(credit, installments)


@router.get("/", response_model=list[CreditOut])
async def list_credits(
    status_filter: Optional[str] = None,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    q = db.query(SpecialCredit)
    if status_filter:
        q = q.filter(SpecialCredit.status == status_filter.upper())
    credits = q.order_by(SpecialCredit.disbursed_date.desc(), SpecialCredit.created_at.desc()).all()

    result = []
    for c in credits:
        insts  = db.query(CreditInstallment).filter_by(credit_id=c.id).all()
        draws  = db.query(CreditDraw).filter_by(credit_id=c.id).all()
        result.append(_build_out(c, insts, draws))
    return result


@router.get("/{credit_id}", response_model=CreditOut)
async def get_credit(
    credit_id: str,
    current_user: TokenData = Depends(require_role("admin", "supervisor")),
    db: Session = Depends(get_db),
):
    credit = db.query(SpecialCredit).filter_by(id=credit_id).first()
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found.")
    insts = db.query(CreditInstallment).filter_by(credit_id=credit.id).all()
    draws = db.query(CreditDraw).filter_by(credit_id=credit.id).all()
    return _build_out(credit, insts, draws)


@router.patch("/{credit_id}/installments/{installment_id}/pay", response_model=CreditOut)
async def mark_paid(
    credit_id: str,
    installment_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    credit = db.query(SpecialCredit).filter_by(id=credit_id).first()
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found.")
    if credit.status == CreditStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot update a cancelled credit.")

    inst = db.query(CreditInstallment).filter_by(id=installment_id, credit_id=credit_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Installment not found.")
    if inst.paid_at:
        raise HTTPException(status_code=400, detail="Installment already marked as paid.")

    inst.paid_at = date_type.today()
    inst.received_by = current_user.username

    # Auto-complete credit when all installments are paid
    all_insts = db.query(CreditInstallment).filter_by(credit_id=credit_id).all()
    if all(i.paid_at for i in all_insts):
        credit.status = CreditStatus.COMPLETED

    db.commit()
    draws = db.query(CreditDraw).filter_by(credit_id=credit_id).all()
    return _build_out(credit, all_insts, draws)


@router.patch("/{credit_id}/cancel", response_model=CreditOut)
async def cancel_credit(
    credit_id: str,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    credit = db.query(SpecialCredit).filter_by(id=credit_id).first()
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found.")
    if credit.status == CreditStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed credit.")

    credit.status = CreditStatus.CANCELLED
    db.commit()
    insts = db.query(CreditInstallment).filter_by(credit_id=credit.id).all()
    draws = db.query(CreditDraw).filter_by(credit_id=credit.id).all()
    return _build_out(credit, insts, draws)


# ── Credit Draws ──────────────────────────────────────────────────────────────

class DrawIn(BaseModel):
    amount: float
    notes:  Optional[str] = None


@router.post("/{credit_id}/draws", response_model=CreditOut, status_code=status.HTTP_201_CREATED)
async def add_draw(
    credit_id: str,
    payload:      DrawIn,
    current_user: TokenData = Depends(require_role("admin")),
    db:           Session   = Depends(get_db),
):
    credit = db.query(SpecialCredit).filter_by(id=credit_id).first()
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found.")
    if credit.status != CreditStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Can only add draws to an active credit.")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")

    interval_min = int(_get_setting(db, "credit_draw_interval_minutes"))
    max_per_day  = int(_get_setting(db, "credit_draw_max_per_day"))
    max_amount   = float(_get_setting(db, "credit_draw_max_amount"))

    now_pht  = datetime.now(tz=PHT)
    today    = now_pht.date()
    all_draws = db.query(CreditDraw).filter_by(credit_id=credit_id).all()

    # Cooldown check
    if all_draws and interval_min > 0:
        last = max(all_draws, key=lambda d: d.created_at)
        last_pht = last.created_at.astimezone(PHT) if last.created_at.tzinfo else last.created_at.replace(tzinfo=PHT)
        elapsed = (now_pht - last_pht).total_seconds() / 60
        if elapsed < interval_min:
            remaining = int(interval_min - elapsed) + 1
            raise HTTPException(status_code=429, detail=f"Too soon. Wait {remaining} more minute(s) before next draw.")

    # Daily limit check
    today_draws = [d for d in all_draws if d.created_at and d.created_at.astimezone(PHT).date() == today]
    if max_per_day > 0 and len(today_draws) >= max_per_day:
        raise HTTPException(status_code=429, detail=f"Daily draw limit ({max_per_day}) reached for this credit.")

    # Max amount check
    if max_amount > 0 and payload.amount > max_amount:
        raise HTTPException(status_code=400, detail=f"Draw amount exceeds max allowed ({max_amount:,.2f}).")

    draw = CreditDraw(
        id=uuid.uuid4(),
        credit_id=credit.id,
        amount=payload.amount,
        notes=payload.notes,
        created_by=current_user.username,
    )
    db.add(draw)
    db.commit()

    insts = db.query(CreditInstallment).filter_by(credit_id=credit.id).all()
    draws = db.query(CreditDraw).filter_by(credit_id=credit.id).all()
    return _build_out(credit, insts, draws)


# ── Admin Settings ────────────────────────────────────────────────────────────

@router.get("/settings/draw-rules", response_model=CreditDrawRules)
async def get_draw_rules(
    current_user: TokenData = Depends(require_role("admin")),
    db:           Session   = Depends(get_db),
):
    return CreditDrawRules(
        interval_minutes=int(_get_setting(db, "credit_draw_interval_minutes")),
        max_per_day=int(_get_setting(db, "credit_draw_max_per_day")),
        max_amount=float(_get_setting(db, "credit_draw_max_amount")),
    )


@router.patch("/settings/draw-rules", response_model=CreditDrawRules)
async def update_draw_rules(
    payload:      CreditDrawRules,
    current_user: TokenData = Depends(require_role("admin")),
    db:           Session   = Depends(get_db),
):
    updates = {
        "credit_draw_interval_minutes": str(payload.interval_minutes),
        "credit_draw_max_per_day":      str(payload.max_per_day),
        "credit_draw_max_amount":       str(payload.max_amount),
    }
    for key, value in updates.items():
        row = db.query(AppSetting).filter_by(key=key).first()
        if row:
            row.value      = value
            row.updated_by = current_user.username
        else:
            db.add(AppSetting(key=key, value=value, updated_by=current_user.username))
    db.commit()
    return CreditDrawRules(
        interval_minutes=payload.interval_minutes,
        max_per_day=payload.max_per_day,
        max_amount=payload.max_amount,
    )
