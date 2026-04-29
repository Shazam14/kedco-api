"""
Shared fixtures for API route integration tests.

Uses a dedicated kedco_test_db (separate from production kedco_db) so prod
data is never touched. Tables are created once per test session; each test
truncates before it runs to start from a clean slate.
"""
import os

# Force the test DB BEFORE the app imports settings.
os.environ["DATABASE_URL"] = "postgresql://kedco:kedco_secure_forex@localhost:5432/kedco_test_db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.models.transaction import RiderDispatch, DispatchStatus
from app.core.today import get_today


TEST_DB_URL = "postgresql+psycopg://kedco:kedco_secure_forex@localhost:5432/kedco_test_db"
test_engine = create_engine(TEST_DB_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def db():
    """Per-test session, with all tables truncated before yield."""
    with test_engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """TestClient where each request gets its own session bound to the test DB."""
    def _override_get_db():
        s = TestSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _make_user(db, username: str, role: str, full_name: str | None = None) -> User:
    user = User(
        username=username,
        full_name=full_name or username,
        password_hash=hash_password("password"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db) -> User:
    return _make_user(db, "admintest", "admin", "Admin Test")


@pytest.fixture
def supervisor_user(db) -> User:
    return _make_user(db, "supervisortest", "supervisor", "Supervisor Test")


@pytest.fixture
def rider_user(db) -> User:
    return _make_user(db, "ridertest", "rider", "Rider Test")


def auth_header(username: str, role: str) -> dict:
    """Mint a JWT Bearer header. Mirrors what auth.login produces."""
    token = create_access_token({"sub": username, "role": role, "full_name": username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_dispatch(db, rider_user):
    """Factory: create an IN_FIELD dispatch for the seeded rider."""
    import uuid

    def _make(cash_php: float = 300_000.0, **overrides) -> RiderDispatch:
        dispatch = RiderDispatch(
            id=uuid.uuid4(),
            date=get_today(),
            rider_username=rider_user.username,
            rider_name=rider_user.full_name,
            status=DispatchStatus.IN_FIELD,
            dispatch_time="09:00 AM",
            cash_php=cash_php,
            dispatched_by="admintest",
            **overrides,
        )
        db.add(dispatch)
        db.commit()
        db.refresh(dispatch)
        return dispatch

    return _make
