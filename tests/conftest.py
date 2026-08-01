import os
import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27018/resumedraft_test")

from app.main import app
from app.auth import get_current_user
from app.db.mongo import db

FAKE_UID = "test-uid-12345"


def fake_user():
    return {"uid": FAKE_UID, "email": "test@example.com"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def override_auth():
    """Every test runs as an authenticated fake user by default -- verify_id_token is never
    called, so tests don't need a real Firebase ID token. Endpoints that specifically test
    unauthenticated access clear this override themselves."""
    app.dependency_overrides[get_current_user] = fake_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
async def clean_db():
    """Reconnect fresh every test. pytest-anyio gives each test function its own event loop,
    and Motor's AsyncIOMotorClient is bound to whichever loop was running when it was
    created -- reusing a client across tests fails with 'Event loop is closed' once the
    first test's loop tears down. The connection itself is cheap; this trades a little
    per-test overhead for not fighting event-loop lifetime."""
    await db.connect()
    yield
    for collection in ["company_watchlists", "resume_snapshots", "artifacts"]:
        await db.db[collection].delete_many({"uid": FAKE_UID})
    db.client.close()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
