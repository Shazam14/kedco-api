from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date, datetime
import uuid

from app.core.database import get_db
from app.models.transaction import Transaction
from app.models.currency import DailyRate, DailyPosition
from app.schemas.forex import TransactionIn, TransactionOut
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _get_daily_avg(currency_code: str, today: date, db: Session) -> float:
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
    current_user: TokenData = Depends(require_role("admin", "cashier")),
    db: Session = Depends(get_db),
):
    today = date.today()
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
    )


@router.get("/today", response_model=list[TransactionOut])
async def get_today_transactions(
    current_user: TokenData = Depends(require_role("admin", "cashier")),
    db: Session = Depends(get_db),
):
    rows = db.query(Transaction).filter_by(date=date.today()).order_by(
        Transaction.created_at.desc()
    ).all()
    return [
        TransactionOut(
            id=r.id, time=r.time, type=r.type, source=r.source,
            currency=r.currency_code, foreign_amt=r.foreign_amt,
            rate=r.rate, php_amt=r.php_amt, than=r.than,
            cashier=r.cashier, customer=r.customer,
        )
        for r in rows
    ]
