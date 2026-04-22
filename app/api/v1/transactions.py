from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, date
import uuid

from app.core.database import get_db
from app.core.today import get_today
from app.models.transaction import Transaction
from app.models.audit import AuditLog
from app.models.currency import DailyRate, DailyPosition
from app.schemas.forex import TransactionIn, TransactionOut, TransactionPatch
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _get_daily_avg(currency_code: str, today, db: Session) -> float:
    """
    Compute today's daily avg cost for a currency using DB data.
    Needed to calculate THAN on sell transactions.
    """
    rate_row = db.query(DailyRate).filter_by(date=today, currency_code=currency_code).first()
    if not rate_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No rate set for {currency_code} today. Ask admin to set rates first.",
        )

    position_row = db.query(DailyPosition).filter_by(date=today, currency_code=currency_code).first()
    carry_in = CarryIn(
        qty=position_row.carry_in_qty if position_row else 0,
        rate=position_row.carry_in_rate if position_row else rate_row.buy_rate,
    )

    # Get all buys recorded today for this currency
    buys_today = db.query(Transaction).filter_by(
        date=today, currency_code=currency_code, type="BUY"
    ).all()
    today_buys = [TodayBuy(qty=t.foreign_amt, rate=t.rate) for t in buys_today]

    result = compute_position(carry_in, today_buys, rate_row.sell_rate)
    return result.daily_avg_cost


@router.post("/", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    txn: TransactionIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "rider")),
    db: Session = Depends(get_db),
):
    today = get_today()
    now = datetime.now().strftime("%I:%M %p")

    daily_avg = _get_daily_avg(txn.currency, today, db)
    php_amt = round(txn.foreign_amt * txn.rate, 2)
    than = round((txn.rate - daily_avg) * txn.foreign_amt, 2) if txn.type == "SELL" else 0.0

    # Generate ID: OR-XXXXXXXX for counter, RD-XXXXXXXX for rider
    prefix = "RD" if txn.source == "RIDER" else "OR"
    txn_id = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    record = Transaction(
        id=txn_id,
        date=today,
        time=now,
        type=txn.type,
        source=txn.source,
        currency_code=txn.currency,
        foreign_amt=txn.foreign_amt,
        rate=txn.rate,
        php_amt=php_amt,
        daily_avg_cost=daily_avg,
        than=than,
        cashier=current_user.username,
        customer=txn.customer,
        payment_mode=txn.payment_mode or "CASH",
        bank_id=txn.bank_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return TransactionOut(
        id=record.id,
        time=record.time,
        type=record.type,
        source=record.source,
        currency=record.currency_code,
        foreign_amt=record.foreign_amt,
        rate=record.rate,
        php_amt=record.php_amt,
        than=record.than,
        cashier=record.cashier,
        customer=record.customer,
        payment_mode=record.payment_mode,
        bank_id=record.bank_id,
    )


@router.get("/today", response_model=list[TransactionOut])
async def get_today_transactions(
    current_user: TokenData = Depends(require_role("admin", "cashier", "rider")),
    db: Session = Depends(get_db),
):
    rows = db.query(Transaction).filter_by(date=get_today()).order_by(
        Transaction.created_at.desc()
    ).all()
    return [
        TransactionOut(
            id=r.id, time=r.time, type=r.type, source=r.source,
            currency=r.currency_code, foreign_amt=r.foreign_amt,
            rate=r.rate, php_amt=r.php_amt, than=r.than,
            cashier=r.cashier, customer=r.customer,
            payment_mode=r.payment_mode, bank_id=r.bank_id,
        )
        for r in rows
    ]


@router.patch("/{txn_id}", response_model=TransactionOut)
async def edit_transaction(
    txn_id: str,
    patch: TransactionPatch,
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    record = db.query(Transaction).filter_by(id=txn_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if record.date != get_today():
        raise HTTPException(status_code=403, detail="Only same-day transactions can be edited")

    old_snapshot = {
        "customer":     record.customer,
        "payment_mode": str(record.payment_mode),
        "rate":         record.rate,
        "foreign_amt":  record.foreign_amt,
        "php_amt":      record.php_amt,
        "than":         record.than,
    }

    if patch.customer is not None:
        record.customer = patch.customer or None
    if patch.payment_mode is not None:
        record.payment_mode = patch.payment_mode
    if patch.rate is not None:
        record.rate = patch.rate
    if patch.foreign_amt is not None:
        record.foreign_amt = patch.foreign_amt

    # Recompute derived fields whenever rate or foreign_amt changed
    if patch.rate is not None or patch.foreign_amt is not None:
        record.php_amt = round(record.foreign_amt * record.rate, 2)
        if str(record.type) == "SELL":
            record.than = round((record.rate - record.daily_avg_cost) * record.foreign_amt, 2)

    new_snapshot = {
        "customer":     record.customer,
        "payment_mode": str(record.payment_mode),
        "rate":         record.rate,
        "foreign_amt":  record.foreign_amt,
        "php_amt":      record.php_amt,
        "than":         record.than,
    }

    db.add(AuditLog(
        id=uuid.uuid4(),
        table_name="transactions",
        record_id=txn_id,
        action="UPDATE",
        changed_by=current_user.username,
        old_value=old_snapshot,
        new_value=new_snapshot,
    ))
    db.commit()
    db.refresh(record)

    return TransactionOut(
        id=record.id, time=record.time, type=record.type, source=record.source,
        currency=record.currency_code, foreign_amt=record.foreign_amt,
        rate=record.rate, php_amt=record.php_amt, than=record.than,
        cashier=record.cashier, customer=record.customer,
        payment_mode=record.payment_mode, bank_id=record.bank_id,
    )
