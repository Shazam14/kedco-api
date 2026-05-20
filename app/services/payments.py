"""
Slice-aware payment math.

A Transaction may have N TxnPayment slices (split payments). Each slice
carries its own RECEIVED/PENDING status. The Transaction.payment_status
column is a rollup: PENDING if any slice is pending. That rollup is fine
as a chip/badge but is WRONG for money math — a SELL with a CASH-RECEIVED
+ CHEQUE-PENDING split has half its peso physically in hand right now.

All consumers that sum php_amt with a "received only" filter MUST use
received_php(t) (or its share variant for proportional fields like than).
Without it the cash slice of a partially-pending txn vanishes from totals.

Incident: 2026-05-18, RD-7CFB1A58 — rider SELL ₱60,760 split as
₱10,760 CASH (RECEIVED) + ₱50,000 CHEQUE (PENDING). Parent stamped PENDING,
so the rider's PHP carry never reflected the ₱10,760 cash in hand.
"""
from app.models.transaction import PaymentStatus, Transaction


def received_php(t: Transaction) -> float:
    """PHP physically received on this txn right now (slice-aware)."""
    if t.payments:
        return sum(p.amount_php for p in t.payments if p.status == PaymentStatus.RECEIVED)
    return t.php_amt if t.payment_status != PaymentStatus.PENDING else 0.0


def pending_php(t: Transaction) -> float:
    """PHP still owed/uncleared on this txn (slice-aware)."""
    if t.payments:
        return sum(p.amount_php for p in t.payments if p.status == PaymentStatus.PENDING)
    return t.php_amt if t.payment_status == PaymentStatus.PENDING else 0.0


def received_share(t: Transaction) -> float:
    """
    Received fraction in [0, 1] for proportional fields (e.g. than).
    Zero-amount txns (EXCESS) return 0 to avoid div-by-zero.
    """
    if t.php_amt <= 0:
        return 0.0
    return received_php(t) / t.php_amt
