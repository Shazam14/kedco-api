from datetime import date
from pathlib import Path

_MOCK_DATE_FILE = Path(__file__).resolve().parent.parent.parent / "mock_date.txt"


def get_today() -> date:
    if _MOCK_DATE_FILE.exists():
        try:
            return date.fromisoformat(_MOCK_DATE_FILE.read_text().strip())
        except ValueError:
            pass
    return date.today()


def set_mock_date(d: date) -> None:
    _MOCK_DATE_FILE.write_text(d.isoformat())


def clear_mock_date() -> None:
    _MOCK_DATE_FILE.unlink(missing_ok=True)


def get_mock_date() -> date | None:
    if _MOCK_DATE_FILE.exists():
        try:
            return date.fromisoformat(_MOCK_DATE_FILE.read_text().strip())
        except ValueError:
            pass
    return None
