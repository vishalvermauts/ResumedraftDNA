import pytest


@pytest.mark.anyio
async def test_health_endpoint(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
