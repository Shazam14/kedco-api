"""
Locks in the rate_set / position_set flags the cashier setup-status guard
depends on.

The website's /api/counter/setup-status proxy derives `ratesSet` from
GET /api/v1/currencies/ (looking for any rate_set=true) and `positionsSet`
from GET /api/v1/positions/today (looking for any position_set=true).
If either of those flags drifts from the real DB state, the cashier guard
either lies (false-OK → cashier transacts on stale data) or false-locks
(false-FAIL → cashier can't work even when admin set everything up).
Both modes have happened before in adjacent code paths.
"""
from datetime import date

import pytest
from sqlalchemy import text

from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition


@pytest.fixture
def seed_currencies(db):
    """Two active currencies — USD and JPY — so we can flip flags per-currency."""
    db.add_all([
        Currency(code="USD", name="US Dollar", flag="🇺🇸",
                 category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y"),
        Currency(code="JPY", name="Japanese Yen", flag="🇯🇵",
                 category=CurrencyCategory.MAIN, decimal_places=0, sort_order=2, is_active="Y"),
    ])
    db.commit()
    return ["USD", "JPY"]


# ── /currencies/ → rate_set ──────────────────────────────────────────────────

class TestCurrenciesRateSetFlag:

    def test_rate_set_false_when_no_rate_for_today(self, client, seed_currencies, admin_user):
        res = client.get("/api/v1/currencies/", headers=_auth("admintest", "admin"))
        assert res.status_code == 200
        data = res.json()
        assert all(c["rate_set"] is False for c in data)
        assert all(c["today_buy_rate"] is None for c in data)

    def test_rate_set_true_for_currencies_with_a_rate_today(
        self, client, db, seed_currencies, admin_user
    ):
        from app.core.today import get_today
        db.add(DailyRate(
            date=get_today(), currency_code="USD",
            buy_rate=57.0, sell_rate=58.0, set_by="admintest",
        ))
        db.commit()

        res = client.get("/api/v1/currencies/", headers=_auth("admintest", "admin"))
        data = {c["code"]: c for c in res.json()}
        assert data["USD"]["rate_set"] is True
        assert data["USD"]["today_buy_rate"] == 57.0
        assert data["JPY"]["rate_set"] is False  # only USD set


# ── /positions/today → position_set ──────────────────────────────────────────

class TestPositionsPositionSetFlag:

    def test_position_set_false_when_no_position_for_today(
        self, client, seed_currencies, admin_user
    ):
        res = client.get("/api/v1/positions/today", headers=_auth("admintest", "admin"))
        assert res.status_code == 200
        data = res.json()
        assert all(p["position_set"] is False for p in data)

    def test_position_set_true_for_currencies_with_a_position_today(
        self, client, db, seed_currencies, admin_user
    ):
        from app.core.today import get_today
        db.add(DailyPosition(
            date=get_today(), currency_code="USD",
            carry_in_qty=1000.0, carry_in_rate=57.5,
        ))
        db.commit()

        res = client.get("/api/v1/positions/today", headers=_auth("admintest", "admin"))
        data = {p["code"]: p for p in res.json()}
        assert data["USD"]["position_set"] is True
        assert data["USD"]["carry_in_qty"] == 1000.0
        assert data["JPY"]["position_set"] is False


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestSetupStatusEndpointsAuth:
    """The proxy hits these as the logged-in cashier — they must allow the role."""

    def test_currencies_allows_cashier(self, client, seed_currencies, cashier_user):
        res = client.get("/api/v1/currencies/", headers=_auth("cashiertest", "cashier"))
        assert res.status_code == 200

    def test_positions_today_allows_cashier(self, client, seed_currencies, cashier_user):
        res = client.get("/api/v1/positions/today", headers=_auth("cashiertest", "cashier"))
        assert res.status_code == 200


def _auth(username: str, role: str) -> dict:
    from tests.conftest import auth_header
    return auth_header(username, role)
