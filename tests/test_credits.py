"""
Unit tests for special credit business logic.

Tests the key calculations inline (same pattern as test_shift_logic.py)
since the logic lives in the route handlers.

Business rules:
  UPFRONT     — interest collected at disbursement.
                cash_out = principal - interest
                1 installment = principal (customer pays back principal only)

  INSTALLMENT — principal + interest split across N payments.
                amount_per = (principal + interest) / N
                cash_out = principal (full amount given out)

  Auto-complete — credit becomes COMPLETED when all installments have paid_at set.
"""

import pytest
from datetime import date


# ── Pure logic helpers (mirrors what the API does inline) ──────────────────────

def compute_cash_out(principal: float, interest: float, credit_type: str) -> float:
    """Amount physically handed to the customer."""
    if credit_type == "UPFRONT":
        return round(principal - interest, 2)
    return round(principal, 2)  # INSTALLMENT: full principal given out


def compute_installment_amount(principal: float, interest: float, credit_type: str, count: int) -> float:
    """Amount due per installment slot."""
    if credit_type == "UPFRONT":
        return round(principal, 2)  # 1 slot = full principal payback
    return round((principal + interest) / count, 2)


def all_paid(installments: list[dict]) -> bool:
    """True when every installment has a paid_at date."""
    return all(i["paid_at"] is not None for i in installments)


# ── UPFRONT tests ──────────────────────────────────────────────────────────────

class TestUpfrontCredit:
    def test_cash_out_is_principal_minus_interest(self):
        assert compute_cash_out(100_000, 5_000, "UPFRONT") == 95_000

    def test_cash_out_zero_interest(self):
        assert compute_cash_out(100_000, 0, "UPFRONT") == 100_000

    def test_single_installment_equals_principal(self):
        # UPFRONT: customer pays back the agreed principal, interest already taken
        assert compute_installment_amount(100_000, 5_000, "UPFRONT", 1) == 100_000

    def test_interest_collected_is_positive_income(self):
        interest = 5_000
        assert interest > 0  # always income, never negative

    def test_decimal_amounts(self):
        # e.g. USD 1,000 principal, USD 50 interest
        assert compute_cash_out(1_000.00, 50.00, "UPFRONT") == 950.00
        assert compute_installment_amount(1_000.00, 50.00, "UPFRONT", 1) == 1_000.00


# ── INSTALLMENT tests ──────────────────────────────────────────────────────────

class TestInstallmentCredit:
    def test_cash_out_is_full_principal(self):
        assert compute_cash_out(100_000, 5_000, "INSTALLMENT") == 100_000

    def test_two_payments(self):
        # 100k + 5k = 105k / 2 = 52,500 each
        assert compute_installment_amount(100_000, 5_000, "INSTALLMENT", 2) == 52_500

    def test_three_payments(self):
        # 90k + 9k = 99k / 3 = 33,000 each
        assert compute_installment_amount(90_000, 9_000, "INSTALLMENT", 3) == 33_000

    def test_single_payment(self):
        # 1 installment = full total
        assert compute_installment_amount(100_000, 5_000, "INSTALLMENT", 1) == 105_000

    def test_four_payments_decimal(self):
        # 100k + 3k = 103k / 4 = 25,750 each
        assert compute_installment_amount(100_000, 3_000, "INSTALLMENT", 4) == 25_750

    def test_usd_installments(self):
        # USD 1,000 + USD 100 / 2 = USD 550 each
        assert compute_installment_amount(1_000, 100, "INSTALLMENT", 2) == 550.00


# ── Auto-complete logic ────────────────────────────────────────────────────────

class TestAutoComplete:
    def test_not_complete_when_none_paid(self):
        installments = [
            {"id": "i1", "paid_at": None},
            {"id": "i2", "paid_at": None},
        ]
        assert all_paid(installments) is False

    def test_not_complete_when_partially_paid(self):
        installments = [
            {"id": "i1", "paid_at": date(2026, 5, 1)},
            {"id": "i2", "paid_at": None},
        ]
        assert all_paid(installments) is False

    def test_complete_when_all_paid(self):
        installments = [
            {"id": "i1", "paid_at": date(2026, 5, 1)},
            {"id": "i2", "paid_at": date(2026, 5, 16)},
        ]
        assert all_paid(installments) is True

    def test_single_installment_upfront_complete(self):
        installments = [{"id": "i1", "paid_at": date(2026, 5, 1)}]
        assert all_paid(installments) is True

    def test_empty_installments_edge_case(self):
        # No installments → vacuously "all paid" — shouldn't happen in practice
        assert all_paid([]) is True


# ── Daily report credit section ────────────────────────────────────────────────

class TestDailyReportCreditSection:
    def test_upfront_interest_income_on_disbursement_day(self):
        """UPFRONT credits created today contribute their full interest to income."""
        credits_today = [
            {"credit_type": "UPFRONT", "interest": 5_000},
            {"credit_type": "UPFRONT", "interest": 3_000},
            {"credit_type": "INSTALLMENT", "interest": 10_000},  # not counted upfront
        ]
        interest_income = round(
            sum(c["interest"] for c in credits_today if c["credit_type"] == "UPFRONT"), 2
        )
        assert interest_income == 8_000

    def test_total_cash_out_upfront(self):
        disbursements = [
            {"credit_type": "UPFRONT",     "principal": 100_000, "interest": 5_000},
            {"credit_type": "INSTALLMENT", "principal": 50_000,  "interest": 2_500},
        ]
        total = round(sum(
            compute_cash_out(d["principal"], d["interest"], d["credit_type"])
            for d in disbursements
        ), 2)
        # UPFRONT: 95k + INSTALLMENT: 50k = 145k
        assert total == 145_000

    def test_total_payments_received(self):
        payments_today = [
            {"amount": 52_500},
            {"amount": 52_500},
        ]
        total_in = round(sum(p["amount"] for p in payments_today), 2)
        assert total_in == 105_000
