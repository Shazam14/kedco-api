"""
Unit tests for app/core/today.py — get_today() and helpers.

Pure Python, no database. Uses tmp_path + monkeypatch so tests never
touch the real mock_date.txt at the project root.
"""

import pytest
from datetime import date
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _patch_file(monkeypatch, tmp_path: Path) -> Path:
    """Redirect _MOCK_DATE_FILE to a temp path and return it."""
    import app.core.today as mod
    fake = tmp_path / "mock_date.txt"
    monkeypatch.setattr(mod, "_MOCK_DATE_FILE", fake)
    return fake


# ── get_today() ───────────────────────────────────────────────────────────────

class TestGetToday:
    def test_returns_real_date_when_no_file(self, monkeypatch, tmp_path):
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import get_today
        assert get_today() == date.today()

    def test_returns_mock_date_when_file_exists(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("2026-04-06")
        from app.core.today import get_today
        assert get_today() == date(2026, 4, 6)

    def test_falls_back_to_real_date_on_invalid_content(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("not-a-date")
        from app.core.today import get_today
        assert get_today() == date.today()

    def test_falls_back_to_real_date_on_empty_file(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("")
        from app.core.today import get_today
        assert get_today() == date.today()


# ── set_mock_date() ───────────────────────────────────────────────────────────

class TestSetMockDate:
    def test_writes_iso_date_to_file(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        from app.core.today import set_mock_date
        set_mock_date(date(2026, 4, 6))
        assert f.read_text() == "2026-04-06"

    def test_overwrites_existing_file(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("2026-01-01")
        from app.core.today import set_mock_date
        set_mock_date(date(2026, 4, 10))
        assert f.read_text() == "2026-04-10"


# ── clear_mock_date() ─────────────────────────────────────────────────────────

class TestClearMockDate:
    def test_removes_file(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("2026-04-06")
        from app.core.today import clear_mock_date
        clear_mock_date()
        assert not f.exists()

    def test_no_error_when_file_absent(self, monkeypatch, tmp_path):
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import clear_mock_date
        clear_mock_date()  # should not raise


# ── get_mock_date() ───────────────────────────────────────────────────────────

class TestGetMockDate:
    def test_returns_none_when_no_file(self, monkeypatch, tmp_path):
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import get_mock_date
        assert get_mock_date() is None

    def test_returns_date_when_file_exists(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("2026-04-07")
        from app.core.today import get_mock_date
        assert get_mock_date() == date(2026, 4, 7)

    def test_returns_none_on_invalid_content(self, monkeypatch, tmp_path):
        f = _patch_file(monkeypatch, tmp_path)
        f.write_text("garbage")
        from app.core.today import get_mock_date
        assert get_mock_date() is None


# ── round-trip: set → get → clear ────────────────────────────────────────────

class TestRoundTrip:
    def test_set_then_get_today_returns_mock(self, monkeypatch, tmp_path):
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import set_mock_date, get_today
        set_mock_date(date(2026, 4, 8))
        assert get_today() == date(2026, 4, 8)

    def test_set_then_clear_returns_real_date(self, monkeypatch, tmp_path):
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import set_mock_date, clear_mock_date, get_today
        set_mock_date(date(2026, 4, 8))
        clear_mock_date()
        assert get_today() == date.today()

    def test_advancing_days(self, monkeypatch, tmp_path):
        """Simulate Ken stepping through April 6 → 7 → 8."""
        _patch_file(monkeypatch, tmp_path)
        from app.core.today import set_mock_date, get_today
        for day in [6, 7, 8]:
            set_mock_date(date(2026, 4, day))
            assert get_today() == date(2026, 4, day)
