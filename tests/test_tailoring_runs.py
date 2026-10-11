from unittest.mock import AsyncMock, patch


async def test_tailoring_run_freezes_active_snapshot_and_records_artifacts(client):
    """The product path and a certification run must use the same frozen master."""
    from app.db.mongo import db

    snapshot = await db.db.resume_snapshots.insert_one({
        "uid": "test-uid-12345",
        "firestoreResumeId": "master-1",
        "version": 1,
        "contentHash": "sha256:master-content",
        "structuredData": {
            "personalDetails": {"fullName": "Test User"},
            "employmentHistory": [{"jobTitle": "Coordinator", "company": "Co", "bulletPoints": ["Led project"]}]
        },
        "active": True,
    })

    async def fake_tailor_resume(**kwargs):
        assert kwargs["snapshot_id"] == str(snapshot.inserted_id)
        return {"data": {"tailoredResume": {"personalDetails": {"fullName": "Test User"}}}}

    with patch("app.api.v1.tailoring_runs.tailor_resume", new=AsyncMock(side_effect=fake_tailor_resume)):
        response = await client.post("/v1/tailoring-runs", json={
            "job_id": "frozen-job-1",
            "job_title": "Travel Coordinator",
            "company": "Example Co",
            "description": "Coordinate travel, rosters, compliance records, and stakeholder communication.",
            "artifact_types": ["resume"],
        })

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "passed"
    assert body["snapshot_id"] == str(snapshot.inserted_id)
    assert body["artifacts"][0]["type"] == "resume"
    assert any(stage["name"] == "RESUME_GENERATION" and stage["status"] == "passed" for stage in body["stages"])

    fetched = await client.get(f"/v1/tailoring-runs/{body['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["snapshot_id"] == str(snapshot.inserted_id)


async def test_tailoring_run_records_failure_without_losing_run_history(client):
    from app.db.mongo import db

    await db.db.resume_snapshots.insert_one({
        "uid": "test-uid-12345", "firestoreResumeId": "master-1", "version": 1,
        "structuredData": {
            "personalDetails": {"fullName": "Test User"},
            "employmentHistory": [{"jobTitle": "Coordinator", "company": "Co", "bulletPoints": ["Led project"]}]
        },
        "active": True,
    })

    with patch("app.api.v1.tailoring_runs.tailor_resume", new=AsyncMock(side_effect=RuntimeError("Vertex timeout"))):
        response = await client.post("/v1/tailoring-runs", json={
            "job_id": "frozen-job-2",
            "description": "Coordinate travel, rosters, compliance records, and stakeholder communication.",
            "artifact_types": ["resume"],
        })

    body = response.json()
    assert body["status"] == "failed"
    assert "Vertex timeout" in body["error"]
    assert any(stage["name"] == "FAILED" for stage in body["stages"])
