"""
Rate-setting endpoints accept admin and supervisor (treasurer); other roles 403.

Why: Adminken delegated rate-setting to the treasurer (basing today's rates on
yesterday's stock-ending summary, exactly what /from-carry-in does). The
delegation must hold at the role gate, not just in the UI.
"""
from app.core.today import get_today
from app.models.currency import Currency, CurrencyCategory, DailyPosition, DailyRate
from tests.conftest import auth_header


def _seed_currency(db):
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.commit()


class TestRatesRoleGate:
    def test_supervisor_can_set_today_rates(self, client, supervisor_user, db):
        _seed_currency(db)
        r = client.post(
            "/api/v1/rates/today",
            headers=auth_header("supervisortest", "supervisor"),
            json=[{"code": "USD", "buy_rate": 56.0, "sell_rate": 56.5}],
        )
        assert r.status_code == 201, r.text

        saved = db.query(DailyRate).filter_by(date=get_today(), currency_code="USD").first()
        assert saved is not None
        assert saved.set_by == "supervisortest"

    def test_supervisor_can_use_from_carry_in(self, client, supervisor_user, db):
        _seed_currency(db)
        db.add(DailyPosition(
            date=get_today(), currency_code="USD",
            carry_in_qty=1000.0, carry_in_rate=55.55,
        ))
        db.commit()

        r = client.post(
            "/api/v1/rates/from-carry-in",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 201, r.text

        saved = db.query(DailyRate).filter_by(date=get_today(), currency_code="USD").first()
        assert saved is not None
        assert saved.buy_rate == 55.55
        assert saved.sell_rate == 55.55

    def test_cashier_cannot_set_rates(self, client, cashier_user, db):
        _seed_currency(db)
        r = client.post(
            "/api/v1/rates/today",
            headers=auth_header("cashiertest", "cashier"),
            json=[{"code": "USD", "buy_rate": 56.0, "sell_rate": 56.5}],
        )
        assert r.status_code == 403

    def test_cashier_cannot_use_from_carry_in(self, client, cashier_user, db):
        _seed_currency(db)
        r = client.post(
            "/api/v1/rates/from-carry-in",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 403
