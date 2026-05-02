"""
EOD close authorization.

Owner ruling 2026-05-02: treasurers (role=supervisor) may close the day in
addition to admins, since the operational cut-off (3am-3pm) often lands
when admins aren't on the floor and treasurers are.
"""
from app.core.today import get_today
from app.models.currency import Currency, CurrencyCategory, DailyRate
from tests.conftest import auth_header


def _seed_minimal_rates(db):
    today = get_today()
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(DailyRate(date=today, currency_code="USD", buy_rate=59.0, sell_rate=60.0, set_by="admintest"))
    db.commit()


class TestEODAuthorization:
    def test_admin_can_close(self, client, db, admin_user):
        _seed_minimal_rates(db)
        r = client.post("/api/v1/eod/close", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text

    def test_supervisor_can_close(self, client, db, supervisor_user):
        _seed_minimal_rates(db)
        r = client.post("/api/v1/eod/close", headers=auth_header("supervisortest", "supervisor"))
        assert r.status_code == 200, r.text

    def test_cashier_cannot_close(self, client, db, cashier_user):
        _seed_minimal_rates(db)
        r = client.post("/api/v1/eod/close", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 403

    def test_rider_cannot_close(self, client, db, rider_user):
        _seed_minimal_rates(db)
        r = client.post("/api/v1/eod/close", headers=auth_header("ridertest", "rider"))
        assert r.status_code == 403
