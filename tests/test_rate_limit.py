"""
Integration test for the login rate limiter (5 requests/minute per IP).
Uses a mock DB dependency so no real database is required.
"""

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.limiter import limiter


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
    # First 5 attempts: wrong credentials → 401 (rate limiter lets them through)
    for i in range(5):
        r = client.post("/api/v1/auth/login", data={"username": "x", "password": "x"})
        assert r.status_code == 401, f"Request {i+1} should be 401, got {r.status_code}"

    # 6th attempt: rate limiter blocks it → 429
    r = client.post("/api/v1/auth/login", data={"username": "x", "password": "x"})
    assert r.status_code == 429, f"Request 6 should be 429, got {r.status_code}"
