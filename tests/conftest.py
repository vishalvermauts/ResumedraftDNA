import os
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

# Use the local compose Mongo port by default; CI can still override this with
# MONGODB_URI when it provides an isolated test database.
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/resumedraft_test")

from app.main import app
from app.auth import get_current_user
from app.db.mongo import db

FAKE_UID = "test-uid-12345"


def fake_user():
    return {"uid": FAKE_UID, "email": "test@example.com"}


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
    """Reconnect fresh every test if Mongo is available."""
    if os.getenv("SKIP_MONGO_CLEANUP") == "true":
        yield
        return
    try:
        await asyncio.wait_for(db.connect(), timeout=0.5)
        for collection in ["company_watchlists", "resume_snapshots", "artifacts", "automation_settings", "ai_usage_events", "tailoring_runs"]:
            await db.db[collection].delete_many({"uid": FAKE_UID})
        yield
        for collection in ["company_watchlists", "resume_snapshots", "artifacts", "automation_settings", "ai_usage_events", "tailoring_runs"]:
            await db.db[collection].delete_many({"uid": FAKE_UID})
        db.client.close()
    except Exception:
        yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
