import pytest
from bson import ObjectId
from app.main import app
from app.auth import get_current_user

OTHER_UID = "other-user-uid"


@pytest.mark.anyio
async def test_create_and_list_watchlist_entry(client):
    payload = {
        "companyName": "Acme",
        "careersUrl": "https://acme.example.com/careers",
        "connector": {"type": "greenhouse", "boardToken": "acme", "priority": ["greenhouse"]},
    }
    resp = await client.post("/v1/watchlist", json=payload)
    assert resp.status_code == 200
    item_id = resp.json()["id"]
    assert ObjectId.is_valid(item_id)

    listed = await client.get("/v1/watchlist")
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()]
    assert item_id in ids


@pytest.mark.anyio
async def test_owner_can_delete_own_entry(client):
    payload = {
        "companyName": "Acme",
        "careersUrl": "https://acme.example.com/careers",
        "connector": {"type": "jsonld", "priority": ["jsonld"]},
    }
    created = await client.post("/v1/watchlist", json=payload)
    item_id = created.json()["id"]

    deleted = await client.delete(f"/v1/watchlist/{item_id}")
    assert deleted.status_code == 200

    listed = await client.get("/v1/watchlist")
    assert item_id not in [item["id"] for item in listed.json()]


@pytest.mark.anyio
async def test_cannot_delete_another_users_entry(client):
    payload = {
        "companyName": "Acme",
        "careersUrl": "https://acme.example.com/careers",
        "connector": {"type": "jsonld", "priority": ["jsonld"]},
    }
    created = await client.post("/v1/watchlist", json=payload)
    item_id = created.json()["id"]

    # Switch the auth override to a different user for this one call.
    app.dependency_overrides[get_current_user] = lambda: {"uid": OTHER_UID, "email": "other@example.com"}
    try:
        deleted = await client.delete(f"/v1/watchlist/{item_id}")
        assert deleted.status_code == 404
    finally:
        from app.db.mongo import db
        await db.db.company_watchlists.delete_one({"_id": ObjectId(item_id)})


@pytest.mark.anyio
async def test_deleting_nonexistent_entry_returns_404(client):
    fake_id = str(ObjectId())
    resp = await client.delete(f"/v1/watchlist/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_watchlist_requires_auth(client):
    app.dependency_overrides.pop(get_current_user, None)
    resp = await client.get("/v1/watchlist")
    assert resp.status_code in (401, 403)
