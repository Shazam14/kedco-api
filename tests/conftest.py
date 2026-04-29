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
from app.models.transaction import (
    RiderDispatch, DispatchStatus, Transaction, TxnType, TxnSource,
    PaymentMode, PaymentStatus,
)
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
    """Per-test session, with all tables truncated and route caches cleared."""
    with test_engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    # Clear dashboard's 30s in-memory cache so prior tests don't leak through.
    from app.api.v1 import dashboard as _dashboard_mod
    _dashboard_mod._cache.clear()
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


@pytest.fixture
def cashier_user(db) -> User:
    return _make_user(db, "cashiertest", "cashier", "Cashier Test")


def auth_header(username: str, role: str) -> dict:
    """Mint a JWT Bearer header. Mirrors what auth.login produces."""
    token = create_access_token({"sub": username, "role": role, "full_name": username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_transaction(db):
    """Factory: insert a Transaction row. Defaults: today, COUNTER SELL, RECEIVED."""
    counter = {"n": 0}

    def _make(
        *,
        type: str = "SELL",
        php_amt: float = 10_000.0,
        currency: str = "USD",
        foreign_amt: float = 100.0,
        rate: float = 56.0,
        than: float = 50.0,
        source: str = "COUNTER",
        cashier: str = "cashiertest",
        payment_status: str = "RECEIVED",
        daily_avg_cost: float = 55.5,
        **overrides,
    ) -> Transaction:
        counter["n"] += 1
        txn = Transaction(
            id=overrides.pop("id", f"OR-TEST{counter['n']:04d}"),
            date=overrides.pop("date", get_today()),
            time=overrides.pop("time", "10:00 AM"),
            type=TxnType(type),
            source=TxnSource(source),
            currency_code=currency,
            foreign_amt=foreign_amt,
            rate=rate,
            php_amt=php_amt,
            daily_avg_cost=daily_avg_cost,
            than=than if type == "SELL" else 0,
            cashier=cashier,
            payment_mode=PaymentMode.CASH,
            payment_status=PaymentStatus(payment_status),
            **overrides,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        return txn

    return _make


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
