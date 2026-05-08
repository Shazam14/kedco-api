from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.core.today import get_today
from app.models.transaction import Transaction, TxnPayment
from app.models.audit import AuditLog
from app.models.currency import DailyRate, DailyPosition
from app.models.customer import Customer
from app.schemas.forex import (
    TransactionIn, TransactionOut, TransactionPatch, TransactionBatchIn,
    PaymentSliceIn, PaymentSliceOut,
)
from app.services.forex import compute_position, CarryIn, TodayBuy
from app.api.v1.auth import require_role, TokenData

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _resolve_slices(
    txn: TransactionIn,
    php_amt: float,
    rider_force_pending_noncash: bool,
) -> list[dict]:
    """
    Phase-2/5 backward-compat:
      - payments[] omitted/empty → one slice mirroring legacy payment_mode/payment_status.
      - payments[] provided → use as-is, but rider non-CASH slices (BUY or SELL) are
        force-PENDING (in-hand math depends on cash-only RECEIVED; for BUY a non-cash
        method = "we still owe the customer" until treasurer wires it).
    """
    if txn.payments:
        out = []
        for p in txn.payments:
            method = p.method.upper()
            forced = rider_force_pending_noncash and method != "CASH"
            status = "PENDING" if forced else (p.status or "RECEIVED")
            out.append({
                "method": method,
                "amount_php": round(p.amount_php, 2),
                "status": status,
                "reference_no": p.reference_no,
            })
        return out
    pmode = (txn.payment_mode or "CASH").upper()
    forced = rider_force_pending_noncash and pmode != "CASH"
    status = "PENDING" if forced else (txn.payment_status or "RECEIVED")
    return [{
        "method": pmode,
        "amount_php": round(php_amt, 2),
        "status": status,
        "reference_no": None,
    }]


def _slices_out(record: Transaction) -> list[PaymentSliceOut]:
    out = []
    for p in (record.payments or []):
        out.append(PaymentSliceOut(
            id=p.id,
            method=p.method.value if hasattr(p.method, "value") else str(p.method),
            amount_php=p.amount_php,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            reference_no=p.reference_no,
            received_at=p.received_at,
            confirmed_by=p.confirmed_by,
        ))
    return out


def _to_txn_out(r: Transaction) -> TransactionOut:
    return TransactionOut(
        id=r.id, time=r.time, type=r.type, source=r.source,
        currency=r.currency_code, foreign_amt=r.foreign_amt,
        rate=r.rate, php_amt=r.php_amt, than=r.than,
        cashier=r.cashier, customer=r.customer, customer_id=r.customer_id,
        payment_mode=r.payment_mode, bank_id=r.bank_id,
        official_rate=r.official_rate, referrer=r.referrer,
        payment_tag=r.payment_tag, payment_status=r.payment_status,
        reference_date=r.reference_date,
        batch_id=r.batch_id,
        terminal_id=r.terminal_id, branch_id=r.branch_id,
        date=r.date,
        payments=_slices_out(r),
    )


def _validate_customer_id(customer_id, db: Session) -> None:
    """Reject customer_id values that don't resolve to an active, non-merged customer."""
    if customer_id is None:
        return
    exists = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.is_active.is_(True),
        Customer.merged_into_id.is_(None),
    ).first()
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"customer_id {customer_id} not found or inactive",
        )


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
    if not position_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Carry-in not set for {currency_code}. Please set opening positions first.",
        )
    carry_in = CarryIn(
        qty=position_row.carry_in_qty,
        rate=position_row.carry_in_rate,
    )

    # Get all buys + excess received today for this currency
    # EXCESS entries have rate=0 (free stock) — included so avg cost is correct
    buys_today = db.query(Transaction).filter(
        Transaction.date == today,
        Transaction.currency_code == currency_code,
        Transaction.type.in_(["BUY", "EXCESS"]),
    ).all()
    today_buys = [TodayBuy(qty=t.foreign_amt, rate=t.rate) for t in buys_today]

    result = compute_position(carry_in, today_buys, rate_row.sell_rate)
    return result.daily_avg_cost


@router.post("/", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    txn: TransactionIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    today = get_today()
    now = datetime.now().strftime("%I:%M %p")

    is_excess = txn.type == "EXCESS"

    if is_excess:
        # Excess: foreign currency received for free — no PHP paid, no THAN
        daily_avg = 0.0
        php_amt   = 0.0
        than      = 0.0
    else:
        daily_avg = _get_daily_avg(txn.currency, today, db)
        php_amt   = round(txn.foreign_amt * txn.rate, 2)
        than      = round((txn.rate - daily_avg) * txn.foreign_amt, 2) if txn.type == "SELL" else 0.0

    official_rate = txn.official_rate if not is_excess else None

    _validate_customer_id(txn.customer_id, db)

    # Rider non-CASH slices are always pending (BUY or SELL):
    #   • SELL non-CASH = customer paid via GCash/bank/etc — proceeds haven't landed in
    #     the rider's bag, treasurer confirms when the deposit clears.
    #   • BUY  non-CASH = we still owe the customer (bank transfer, cheque), treasurer
    #     wires it later.
    # Cash-out-of-pocket BUY = RECEIVED (rider already handed over the cash).
    rider_force_pending_noncash = txn.source == "RIDER" and txn.type in ("SELL", "BUY")

    # EXCESS: no money moves, write a single 0-amount CASH slice for shape parity.
    if is_excess:
        slices = [{"method": "CASH", "amount_php": 0.0, "status": "RECEIVED", "reference_no": None}]
    else:
        if txn.payments and abs(sum(p.amount_php for p in txn.payments) - php_amt) > 0.01:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sum of payments ({sum(p.amount_php for p in txn.payments):.2f}) "
                       f"does not match php_amt ({php_amt:.2f})",
            )
        slices = _resolve_slices(txn, php_amt, rider_force_pending_noncash)

    # Aggregate parent fields for backward-compat reads (Phase 4 retires these).
    parent_method = slices[0]["method"]
    parent_status = "PENDING" if any(s["status"] == "PENDING" for s in slices) else "RECEIVED"

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
        rate=0.0 if is_excess else txn.rate,
        php_amt=php_amt,
        daily_avg_cost=daily_avg,
        than=than,
        cashier=current_user.username,
        customer=txn.customer,
        customer_id=txn.customer_id,
        payment_mode=parent_method,
        bank_id=txn.bank_id,
        official_rate=official_rate,
        referrer=txn.referrer or None,
        payment_tag=txn.payment_tag or None,
        payment_status=parent_status,
        reference_date=txn.reference_date,
        note=txn.note or None,
        terminal_id=txn.terminal_id or None,
        branch_id=txn.branch_id or None,
    )
    db.add(record)
    db.flush()

    now_dt = datetime.now()
    for s in slices:
        db.add(TxnPayment(
            txn_id=record.id,
            method=s["method"],
            amount_php=s["amount_php"],
            status=s["status"],
            reference_no=s["reference_no"],
            received_at=now_dt if s["status"] == "RECEIVED" else None,
            confirmed_by=current_user.username if s["status"] == "RECEIVED" else None,
        ))
    db.commit()
    db.refresh(record)

    return _to_txn_out(record)


@router.post("/batch", response_model=list[TransactionOut], status_code=status.HTTP_201_CREATED)
async def create_batch_transaction(
    batch: TransactionBatchIn,
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    today = get_today()
    now = datetime.now().strftime("%I:%M %p")
    batch_uuid = uuid.uuid4()

    _validate_customer_id(batch.customer_id, db)

    records = []
    pmode = (batch.payment_mode or "CASH").upper()
    is_rider = batch.source == "RIDER"
    # Mirror single-txn: rider non-CASH (BUY or SELL) is PENDING until treasurer confirms.
    pending = is_rider and pmode != "CASH"
    slice_status = "PENDING" if pending else "RECEIVED"
    id_prefix = "RD" if is_rider else "OR"
    now_dt = datetime.now()
    for item in batch.items:
        daily_avg = _get_daily_avg(item.currency, today, db)
        php_amt = round(item.foreign_amt * item.rate, 2)
        than = round((item.rate - daily_avg) * item.foreign_amt, 2) if batch.type == "SELL" else 0.0
        txn_id = f"{id_prefix}-{uuid.uuid4().hex[:8].upper()}"
        record = Transaction(
            id=txn_id, date=today, time=now,
            type=batch.type, source=batch.source or "COUNTER",
            currency_code=item.currency, foreign_amt=item.foreign_amt,
            rate=item.rate, php_amt=php_amt,
            daily_avg_cost=daily_avg, than=than,
            cashier=current_user.username, customer=batch.customer,
            customer_id=batch.customer_id,
            payment_mode=pmode,
            bank_id=batch.bank_id,
            official_rate=item.official_rate,
            referrer=batch.referrer or None,
            payment_status=slice_status,
            batch_id=batch_uuid,
            terminal_id=batch.terminal_id or None,
            branch_id=batch.branch_id or None,
        )
        db.add(record)
        db.flush()
        db.add(TxnPayment(
            txn_id=record.id,
            method=pmode,
            amount_php=php_amt,
            status=slice_status,
            received_at=now_dt if slice_status == "RECEIVED" else None,
            confirmed_by=current_user.username if slice_status == "RECEIVED" else None,
        ))
        records.append(record)

    db.commit()
    for r in records:
        db.refresh(r)

    return [_to_txn_out(r) for r in records]


@router.get("/today", response_model=list[TransactionOut])
async def get_today_transactions(
    current_user: TokenData = Depends(require_role("admin", "cashier", "supervisor", "rider")),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction).filter(Transaction.date == get_today())
    if current_user.role == 'cashier':
        q = q.filter(Transaction.cashier == current_user.username)
        # Only show transactions from the current open shift
        from app.models.shift import TellerShift, ShiftStatus
        shift = db.query(TellerShift).filter_by(
            cashier=current_user.username,
            date=get_today(),
            status=ShiftStatus.OPEN,
        ).first()
        if shift:
            q = q.filter(Transaction.created_at >= shift.opened_at)
    rows = q.order_by(Transaction.created_at.desc()).all()
    return [_to_txn_out(r) for r in rows]


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
        "customer":       record.customer,
        "payment_mode":   str(record.payment_mode),
        "bank_id":        record.bank_id,
        "rate":           record.rate,
        "foreign_amt":    record.foreign_amt,
        "php_amt":        record.php_amt,
        "than":           record.than,
        "referrer":       record.referrer,
        "payment_tag":    record.payment_tag,
        "reference_date": str(record.reference_date) if record.reference_date else None,
    }

    if patch.type is not None:
        record.type = patch.type
    if patch.customer is not None:
        record.customer = patch.customer or None
    if patch.customer_id is not None:
        _validate_customer_id(patch.customer_id, db)
        record.customer_id = patch.customer_id
    if patch.payment_mode is not None:
        record.payment_mode = patch.payment_mode
    if patch.bank_id is not None:
        record.bank_id = patch.bank_id
    if patch.referrer is not None:
        record.referrer = patch.referrer or None
    if patch.payment_tag is not None:
        record.payment_tag = patch.payment_tag or None
    if patch.reference_date is not None:
        record.reference_date = patch.reference_date
    if patch.official_rate is not None:
        record.official_rate = patch.official_rate or None
    if patch.rate is not None:
        record.rate = patch.rate
    if patch.foreign_amt is not None:
        record.foreign_amt = patch.foreign_amt

    if patch.rate is not None or patch.foreign_amt is not None or patch.type is not None:
        record.php_amt = round(record.foreign_amt * record.rate, 2)
        if str(record.type) == "SELL":
            record.than = round((record.rate - record.daily_avg_cost) * record.foreign_amt, 2)
        else:
            record.than = 0.0

    new_snapshot = {
        "customer":       record.customer,
        "payment_mode":   str(record.payment_mode),
        "bank_id":        record.bank_id,
        "rate":           record.rate,
        "foreign_amt":    record.foreign_amt,
        "php_amt":        record.php_amt,
        "than":           record.than,
        "referrer":       record.referrer,
        "payment_tag":    record.payment_tag,
        "reference_date": str(record.reference_date) if record.reference_date else None,
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

    return _to_txn_out(record)


class CustomerLinkIn(BaseModel):
    customer_id: Optional[UUID] = None


@router.post("/{txn_id}/customer", response_model=TransactionOut)
async def link_customer_to_transaction(
    txn_id: str,
    body: CustomerLinkIn,
    current_user: TokenData = Depends(require_role("rider", "cashier", "admin", "supervisor")),
    db: Session = Depends(get_db),
):
    """
    Lightweight customer-association endpoint — lets the txn owner attach
    or change a customer on their own same-day txn without going through
    the full admin PATCH flow. Pass customer_id=null to detach.

    Why a separate endpoint: PATCH /{id} is admin-gated and audited because
    it can change rates/amounts. Linking a customer doesn't move money;
    it just labels the txn for aggregation. Rider/cashier need to do this
    inline when a walk-in turns out to be a known loyal customer.
    """
    record = db.query(Transaction).filter_by(id=txn_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if record.date != get_today():
        raise HTTPException(status_code=403, detail="Only same-day transactions can be linked")
    # Owner check — admin/supervisor can relink anyone's; rider/cashier only their own.
    if current_user.role in ("rider", "cashier") and record.cashier != current_user.username:
        raise HTTPException(status_code=403, detail="Cannot link customer on another user's transaction")

    if body.customer_id is not None:
        _validate_customer_id(body.customer_id, db)
    record.customer_id = body.customer_id
    db.commit()
    db.refresh(record)

    return _to_txn_out(record)


@router.get("/commissions", response_model=list[TransactionOut])
async def get_commissions(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: TokenData = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction).filter(Transaction.official_rate.isnot(None))
    if date_from:
        q = q.filter(Transaction.date >= date_from)
    if date_to:
        q = q.filter(Transaction.date <= date_to)
    rows = q.order_by(Transaction.date.desc(), Transaction.created_at.desc()).all()
    return [_to_txn_out(r) for r in rows]
