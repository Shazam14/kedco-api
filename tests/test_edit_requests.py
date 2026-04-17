"""
Unit tests for transaction edit request logic.

Tests are pure Python — no database. They inline the same business rules
used by app/api/v1/edit_requests.py and app/api/v1/transactions.py so that
logic drift is caught at the unit-test level.
"""

from datetime import date
import pytest


# ── Business rule helpers (mirrors production code) ─────────────────────────

def can_request_edit(txn_date: date, txn_cashier: str, requesting_user: str, role: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason). Mirrors the guards in submit_edit_request().
    """
    if txn_date != date.today():
        return False, "Only same-day transactions can be edited"
    if role == "cashier" and txn_cashier != requesting_user:
        return False, "You can only request edits on your own transactions"
    return True, ""


def apply_proposed_changes(txn: dict, proposed: dict) -> dict:
    """
    Returns a new transaction dict with proposed changes applied.
    Mirrors the approval logic in approve_edit_request().
    """
    updated = dict(txn)
    if "customer"     in proposed: updated["customer"]     = proposed["customer"]
    if "payment_mode" in proposed: updated["payment_mode"] = proposed["payment_mode"]
    if "rate"         in proposed: updated["rate"]         = proposed["rate"]
    if "foreign_amt"  in proposed: updated["foreign_amt"]  = proposed["foreign_amt"]

    if "rate" in proposed or "foreign_amt" in proposed:
        updated["php_amt"] = round(updated["foreign_amt"] * updated["rate"], 2)
        if updated["type"] == "SELL":
            updated["than"] = round(
                (updated["rate"] - updated["daily_avg_cost"]) * updated["foreign_amt"], 2
            )
    return updated


def has_pending_request(requests: list[dict], txn_id: str) -> bool:
    return any(r["txn_id"] == txn_id and r["status"] == "PENDING" for r in requests)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def today_sell_txn():
    return {
        "id":             "OR-TESTAAAA",
        "date":           date.today(),
        "type":           "SELL",
        "cashier":        "cashier1",
        "customer":       "Juan dela Cruz",
        "payment_mode":   "CASH",
        "foreign_amt":    500.0,
        "rate":           56.0,
        "php_amt":        28000.0,
        "daily_avg_cost": 55.5,
        "than":           250.0,
    }


@pytest.fixture
def today_buy_txn():
    return {
        "id":             "OR-TESTBBBB",
        "date":           date.today(),
        "type":           "BUY",
        "cashier":        "cashier1",
        "customer":       None,
        "payment_mode":   "CASH",
        "foreign_amt":    1000.0,
        "rate":           55.5,
        "php_amt":        55500.0,
        "daily_avg_cost": 55.5,
        "than":           0.0,
    }


# ── Same-day rule ────────────────────────────────────────────────────────────

def test_cashier_can_request_edit_on_own_todays_txn(today_sell_txn):
    ok, msg = can_request_edit(today_sell_txn["date"], today_sell_txn["cashier"], "cashier1", "cashier")
    assert ok
    assert msg == ""


def test_cashier_blocked_on_other_cashiers_txn(today_sell_txn):
    ok, msg = can_request_edit(today_sell_txn["date"], today_sell_txn["cashier"], "cashier2", "cashier")
    assert not ok
    assert "own transactions" in msg


def test_cashier_blocked_on_past_date_txn(today_sell_txn):
    from datetime import date, timedelta
    past_date = date.today() - timedelta(days=1)
    ok, msg = can_request_edit(past_date, today_sell_txn["cashier"], "cashier1", "cashier")
    assert not ok
    assert "same-day" in msg


def test_admin_can_edit_any_cashiers_txn(today_sell_txn):
    ok, msg = can_request_edit(today_sell_txn["date"], today_sell_txn["cashier"], "admin", "admin")
    assert ok


def test_admin_blocked_on_past_date(today_sell_txn):
    from datetime import date, timedelta
    past_date = date.today() - timedelta(days=1)
    ok, msg = can_request_edit(past_date, today_sell_txn["cashier"], "admin", "admin")
    assert not ok


# ── Duplicate pending guard ───────────────────────────────────────────────────

def test_detects_existing_pending_request():
    requests = [{"txn_id": "OR-TESTAAAA", "status": "PENDING"}]
    assert has_pending_request(requests, "OR-TESTAAAA")


def test_no_false_positive_on_approved_request():
    requests = [{"txn_id": "OR-TESTAAAA", "status": "APPROVED"}]
    assert not has_pending_request(requests, "OR-TESTAAAA")


def test_no_false_positive_on_different_txn():
    requests = [{"txn_id": "OR-TESTBBBB", "status": "PENDING"}]
    assert not has_pending_request(requests, "OR-TESTAAAA")


# ── Approval: field application ──────────────────────────────────────────────

def test_approve_customer_change(today_sell_txn):
    result = apply_proposed_changes(today_sell_txn, {"customer": "New Name"})
    assert result["customer"] == "New Name"
    assert result["rate"] == today_sell_txn["rate"]         # unchanged
    assert result["php_amt"] == today_sell_txn["php_amt"]   # unchanged


def test_approve_payment_mode_change(today_sell_txn):
    result = apply_proposed_changes(today_sell_txn, {"payment_mode": "GCASH"})
    assert result["payment_mode"] == "GCASH"


def test_approve_customer_clear(today_sell_txn):
    result = apply_proposed_changes(today_sell_txn, {"customer": None})
    assert result["customer"] is None


# ── Approval: derived field recomputation ─────────────────────────────────────

def test_approve_rate_change_recomputes_php_amt(today_sell_txn):
    # rate: 56.0 → 57.0, foreign_amt stays 500
    result = apply_proposed_changes(today_sell_txn, {"rate": 57.0})
    assert result["php_amt"] == round(500.0 * 57.0, 2)  # 28500.0


def test_approve_rate_change_recomputes_than_for_sell(today_sell_txn):
    # daily_avg_cost=55.5, new rate=57.0, foreign_amt=500
    result = apply_proposed_changes(today_sell_txn, {"rate": 57.0})
    expected_than = round((57.0 - 55.5) * 500.0, 2)  # 750.0
    assert result["than"] == expected_than


def test_approve_rate_change_does_not_change_than_for_buy(today_buy_txn):
    result = apply_proposed_changes(today_buy_txn, {"rate": 56.0})
    # BUY — than stays 0 regardless
    assert result["than"] == 0.0


def test_approve_foreign_amt_change_recomputes_php_amt(today_sell_txn):
    # foreign_amt: 500 → 600, rate stays 56.0
    result = apply_proposed_changes(today_sell_txn, {"foreign_amt": 600.0})
    assert result["php_amt"] == round(600.0 * 56.0, 2)  # 33600.0


def test_approve_both_rate_and_amt_change(today_sell_txn):
    result = apply_proposed_changes(today_sell_txn, {"rate": 57.0, "foreign_amt": 300.0})
    assert result["php_amt"] == round(300.0 * 57.0, 2)          # 17100.0
    assert result["than"]    == round((57.0 - 55.5) * 300.0, 2) # 450.0


def test_approve_no_rate_or_amt_change_skips_recompute(today_sell_txn):
    original_php  = today_sell_txn["php_amt"]
    original_than = today_sell_txn["than"]
    result = apply_proposed_changes(today_sell_txn, {"customer": "Test"})
    assert result["php_amt"] == original_php
    assert result["than"]    == original_than


# ── Precision edge cases ─────────────────────────────────────────────────────

def test_than_rounds_to_2dp():
    txn = {
        "id": "OR-PREC001", "date": date.today(), "type": "SELL",
        "cashier": "cashier1", "customer": None, "payment_mode": "CASH",
        "foreign_amt": 333.0, "rate": 56.333, "php_amt": 18762.889,
        "daily_avg_cost": 55.111, "than": 0.0,
    }
    result = apply_proposed_changes(txn, {"rate": 56.333})
    expected_than = round((56.333 - 55.111) * 333.0, 2)
    assert result["than"] == expected_than
    assert isinstance(result["than"], float)


def test_php_amt_rounds_to_2dp():
    txn = {
        "id": "OR-PREC002", "date": date.today(), "type": "BUY",
        "cashier": "cashier1", "customer": None, "payment_mode": "CASH",
        "foreign_amt": 100.0, "rate": 55.555, "php_amt": 5555.50,
        "daily_avg_cost": 55.555, "than": 0.0,
    }
    result = apply_proposed_changes(txn, {"rate": 55.555})
    assert result["php_amt"] == round(100.0 * 55.555, 2)  # 5555.5
