from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date as date_type
from typing import Optional
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.models.credit import SpecialCredit, CreditInstallment, CreditType, CreditStatus
from app.api.v1.auth import require_role, TokenData

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_out(credit: SpecialCredit, installments: list[CreditInstallment]) -> CreditOut:
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
    )


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
        insts = db.query(CreditInstallment).filter_by(credit_id=c.id).all()
        result.append(_build_out(c, insts))
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
    return _build_out(credit, insts)


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
    return _build_out(credit, all_insts)


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
    return _build_out(credit, insts)
