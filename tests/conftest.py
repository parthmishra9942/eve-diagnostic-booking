"""Test configuration.

Environment is configured BEFORE the app is imported. By default tests run against a
temporary SQLite file; set TEST_DATABASE_URL to run the same suite against PostgreSQL
(where SELECT ... FOR UPDATE is real, not a no-op).
"""
import os
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="eve-tests-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_tmp_dir}/test.db"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # deliberately unreachable -> exercises fail-open path
os.environ["RATE_LIMIT_STORAGE_URL"] = "memory://"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["AUTH_RATE_LIMIT"] = "5/minute"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["WEBHOOK_DISPATCH_DELAY_SECONDS"] = "0"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.pop("ADMIN_EMAIL", None)

from datetime import datetime, timedelta, timezone  # noqa: E402

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import compute_webhook_signature  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, UserRole  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402

API = "/api/v1"
PASSWORD = "Passw0rdOK"


@pytest_asyncio.fixture(autouse=True)
async def _database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()  # pooled connections must not outlive the per-test event loop


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    res = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def make_user(client: AsyncClient, email: str, role: UserRole = UserRole.USER) -> dict[str, str]:
    """Creates a user (directly via the service for privileged roles) and returns auth headers."""
    async with SessionLocal() as session:
        await AuthService(session).create_user(email=email, full_name="Test User", password=PASSWORD, role=role)
    return await _login(client, email)


@pytest_asyncio.fixture
async def user_headers(client):
    return await make_user(client, "alice@example.com")


@pytest_asyncio.fixture
async def other_headers(client):
    return await make_user(client, "bob@example.com")


@pytest_asyncio.fixture
async def staff_headers(client):
    return await make_user(client, "staff@example.com", UserRole.STAFF)


@pytest_asyncio.fixture
async def catalog(client, staff_headers):
    """One centre offering one test at 1500.00."""
    centre = (await client.post(f"{API}/centres", json={"name": "City Labs", "location": "Indore", "contact": "123"}, headers=staff_headers)).json()
    test = (await client.post(f"{API}/tests", json={"name": "CBC", "category": "Hematology"}, headers=staff_headers)).json()
    link = await client.post(
        f"{API}/centres/{centre['id']}/tests",
        json={"test_id": test["id"], "price": 1500.0, "turnaround_hours": 12},
        headers=staff_headers,
    )
    assert link.status_code == 201, link.text
    return {"centre": centre, "test": test}


def future_iso(days: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


@pytest_asyncio.fixture
async def booking(client, user_headers, catalog):
    res = await client.post(
        f"{API}/bookings",
        json={"centre_id": catalog["centre"]["id"], "test_id": catalog["test"]["id"], "appointment_datetime": future_iso()},
        headers=user_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def manual_webhooks(monkeypatch):
    """Disable automatic webhook dispatch so tests can deliver webhooks themselves."""
    monkeypatch.setattr(settings, "webhook_auto_dispatch", False)


def signed_webhook(*, event_id: str, booking_id: int, transaction_id: str, status: str = "SUCCESS", amount: float = 1500.0) -> dict:
    return {
        "event_id": event_id,
        "booking_id": booking_id,
        "transaction_id": transaction_id,
        "status": status,
        "amount": amount,
        "signature": compute_webhook_signature(
            event_id=event_id, booking_id=booking_id, transaction_id=transaction_id, status=status, amount=amount
        ),
    }
