"""
Integration test for the login rate limiter (50 requests/minute per IP).
Uses a mock DB dependency so no real database is required.
"""

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.limiter import limiter


LOGIN_LIMIT_PER_MINUTE = 50  # keep in sync with @limiter.limit on auth.login


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter._storage.reset()
    yield


@pytest.fixture
def client():
    def mock_db():
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        yield db

    app.dependency_overrides[get_db] = mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_login_rate_limit(client):
    # First N attempts: wrong credentials → 401 (rate limiter lets them through)
    for i in range(LOGIN_LIMIT_PER_MINUTE):
        r = client.post("/api/v1/auth/login", data={"username": "x", "password": "x"})
        assert r.status_code == 401, f"Request {i+1} should be 401, got {r.status_code}"

    # Next attempt: rate limiter blocks it → 429
    r = client.post("/api/v1/auth/login", data={"username": "x", "password": "x"})
    assert r.status_code == 429, f"Request {LOGIN_LIMIT_PER_MINUTE+1} should be 429, got {r.status_code}"
