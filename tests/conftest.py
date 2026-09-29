"""Test setup: Postgres if TEST_DATABASE_URL is set, else file SQLite.

Behaviour is identical for all tested rules (partial unique index uses
sqlite_where too; FOR UPDATE is Postgres-only and skipped on SQLite).
"""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")

from app.api.deps import get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (
    Booking,
    Centre,
    CentreTest,
    DiagnosticTest,
    Payment,
    User,
    WebhookEvent,
)  # noqa: E402

settings.JWT_SECRET = "test-secret"
settings.WEBHOOK_SECRET = "test-webhook-secret"

TEST_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if TEST_URL:
    engine = create_engine(TEST_URL, future=True, pool_pre_ping=True)
    IS_POSTGRES = True
else:
    engine = create_engine(
        "sqlite:///./test_eve.db",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    IS_POSTGRES = False

TestingSession = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if not TEST_URL and os.path.exists("test_eve.db"):
        os.remove("test_eve.db")
    Base.metadata.create_all(bind=engine)
    if not IS_POSTGRES:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA busy_timeout=30000"))
    yield
    Base.metadata.drop_all(bind=engine)
    if not TEST_URL and os.path.exists("test_eve.db"):
        try:
            os.remove("test_eve.db")
        except OSError:
            pass


@pytest.fixture()
def db():
    with TestingSession() as session:
        yield session
        # Truncate everything for isolation (FK order: children first).
        for table in (
            Payment,
            WebhookEvent,
            Booking,
            CentreTest,
            Centre,
            DiagnosticTest,
            User,
        ):
            session.query(table).delete()
        session.commit()


@pytest.fixture()
def client(db: Session):
    """Each request gets its own session (thread-safe); `db` orders truncation."""
    app = create_app()

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------- factories ----------

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


@pytest.fixture()
def make_user(db: Session):
    def _make(
        email: str | None = None, password: str = "password123", is_admin: bool = False
    ) -> User:
        n = _next()
        u = User(
            email=(email or f"user{n}@example.com").lower(),
            hashed_password=hash_password(password),
            full_name=f"User {n}",
            is_admin=is_admin,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    return _make


@pytest.fixture()
def auth_headers(client: TestClient):
    def _headers(user: User, password: str = "password123") -> dict:
        r = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": password}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _headers


@pytest.fixture()
def seed_offer(db: Session):
    """Create one centre + one test + offer. Returns (centre, test, centre_test)."""

    def _make(price: str = "299.00") -> tuple[Centre, DiagnosticTest, CentreTest]:
        from decimal import Decimal

        n = _next()
        c = Centre(name=f"Centre {n}", city="Bengaluru", address="Addr")
        t = DiagnosticTest(name=f"Test {n}", description="desc")
        db.add_all([c, t])
        db.flush()
        offer = CentreTest(centre_id=c.id, test_id=t.id, price=Decimal(price))
        db.add(offer)
        db.commit()
        for o in (c, t, offer):
            db.refresh(o)
        return c, t, offer

    return _make


@pytest.fixture()
def make_booking(db: Session):
    def _make(user: User, offer: CentreTest, status: str = "PENDING") -> Booking:
        b = Booking(
            user_id=user.id,
            centre_id=offer.centre_id,
            test_id=offer.test_id,
            centre_test_id=offer.id,
            appointment_at=datetime.now(timezone.utc) + timedelta(days=1),
            amount=offer.price,
            status=status,
        )
        db.add(b)
        db.commit()
        db.refresh(b)
        return b

    return _make


def sign_webhook(raw: bytes) -> str:
    return hmac.new(settings.WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def webhook_body(**over: object) -> tuple[bytes, dict]:
    payload = {
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
        "provider_reference": f"ref-{uuid.uuid4().hex[:8]}",
        "booking_id": "00000000-0000-0000-0000-000000000000",
        "status": "SUCCESS",
        "amount": "299.00",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(over)
    raw = json.dumps(payload).encode()
    return raw, payload
