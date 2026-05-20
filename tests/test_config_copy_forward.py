"""
POST /config/test-date — when adminken bumps the mock date, copy yesterday's
daily_rates + daily_positions forward so the cashier/treasurer daily-setup
gate doesn't fire on the new day.

Idempotent: if the target date already has rates/positions, skip that table.
If no prior day has data at all, copy nothing (counts stay 0).
"""
from datetime import date
from pathlib import Path

import pytest

from app.models.currency import Currency, DailyRate, DailyPosition, CurrencyCategory
from tests.conftest import auth_header


@pytest.fixture
def _isolate_mock_date_file(monkeypatch, tmp_path):
    """Redirect mock_date.txt to a tmp path so tests don't mutate the real file."""
    import app.core.today as mod
    monkeypatch.setattr(mod, "_MOCK_DATE_FILE", tmp_path / "mock_date.txt")
    yield


def _seed_currencies(db):
    db.add_all([
        Currency(code="USD", name="US Dollar", category=CurrencyCategory.MAIN, sort_order=1),
        Currency(code="JPY", name="Japanese Yen", category=CurrencyCategory.MAIN, sort_order=2),
    ])
    db.commit()


def _seed_day(db, d: date):
    db.add_all([
        DailyRate(date=d, currency_code="USD", buy_rate=56.0, sell_rate=57.0, set_by="seed"),
        DailyRate(date=d, currency_code="JPY", buy_rate=0.36, sell_rate=0.38, set_by="seed"),
        DailyPosition(date=d, currency_code="USD", carry_in_qty=1000, carry_in_rate=56.5),
        DailyPosition(date=d, currency_code="JPY", carry_in_qty=50000, carry_in_rate=0.37),
    ])
    db.commit()


class TestCopyForward:
    def test_copies_when_target_empty(self, client, db, admin_user, _isolate_mock_date_file):
        _seed_currencies(db)
        _seed_day(db, date(2026, 5, 18))

        r = client.post(
            "/api/v1/config/test-date",
            json={"date": "2026-05-19"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["test_date"] == "2026-05-19"
        assert body["rates_copied"]     == 2
        assert body["positions_copied"] == 2
        assert body["rates_source"]     == "2026-05-18"
        assert body["positions_source"] == "2026-05-18"

        # Rows actually written
        assert db.query(DailyRate).filter_by(date=date(2026, 5, 19)).count() == 2
        assert db.query(DailyPosition).filter_by(date=date(2026, 5, 19)).count() == 2

        # Copied rates carry the auto-copy tag
        usd = db.query(DailyRate).filter_by(date=date(2026, 5, 19), currency_code="USD").one()
        assert usd.buy_rate == 56.0
        assert usd.sell_rate == 57.0
        assert usd.set_by == "auto-copy:admintest"

    def test_idempotent_when_target_already_has_data(self, client, db, admin_user, _isolate_mock_date_file):
        _seed_currencies(db)
        _seed_day(db, date(2026, 5, 18))
        # Pre-populate target — copy should skip both tables.
        _seed_day(db, date(2026, 5, 19))

        r = client.post(
            "/api/v1/config/test-date",
            json={"date": "2026-05-19"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rates_copied"]     == 0
        assert body["positions_copied"] == 0
        assert body["rates_source"]     is None
        assert body["positions_source"] is None

        # Still only the original rows — no duplication.
        assert db.query(DailyRate).filter_by(date=date(2026, 5, 19)).count() == 2

    def test_no_prior_data(self, client, db, admin_user, _isolate_mock_date_file):
        _seed_currencies(db)
        # No daily_rates / daily_positions rows at all.

        r = client.post(
            "/api/v1/config/test-date",
            json={"date": "2026-05-19"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rates_copied"]     == 0
        assert body["positions_copied"] == 0
        assert body["rates_source"]     is None
        assert body["positions_source"] is None

    def test_uses_most_recent_prior_date(self, client, db, admin_user, _isolate_mock_date_file):
        """When target is empty, the SOURCE is MAX(date < target), not any random earlier day."""
        _seed_currencies(db)
        # Old gap + a more recent prior day.
        db.add(DailyRate(date=date(2026, 5, 10), currency_code="USD", buy_rate=50.0, sell_rate=51.0, set_by="old"))
        db.add(DailyRate(date=date(2026, 5, 17), currency_code="USD", buy_rate=56.0, sell_rate=57.0, set_by="recent"))
        db.commit()

        r = client.post(
            "/api/v1/config/test-date",
            json={"date": "2026-05-19"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rates_source"] == "2026-05-17"
        # And the value pulled is the recent one, not the old.
        usd_new = db.query(DailyRate).filter_by(date=date(2026, 5, 19), currency_code="USD").one()
        assert usd_new.buy_rate == 56.0

    def test_delete_does_not_trigger_copy(self, client, db, admin_user, _isolate_mock_date_file):
        _seed_currencies(db)
        _seed_day(db, date(2026, 5, 18))

        r = client.delete(
            "/api/v1/config/test-date",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        # Nothing was written to a future date.
        assert db.query(DailyRate).filter(DailyRate.date > date(2026, 5, 18)).count() == 0
