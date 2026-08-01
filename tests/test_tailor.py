"""
Tests the /v1/tailor endpoint's own logic (auth, validation, ObjectId handling, response
shape) with the Gemini call mocked -- real-API correctness belongs in
test_gemini_model_liveness.py, not here. Mocking at this level catches regressions like the
schema/ObjectId/type-branching bugs found this session without incurring API cost or
non-determinism on every CI run.
"""
import pytest
from unittest.mock import AsyncMock, patch


async def test_tailor_without_active_snapshot_returns_404(client):
    resp = await client.post("/v1/tailor/someJobId123?type=resume", json={"description": "A job description"})
    assert resp.status_code == 404
    assert "snapshot" in resp.json()["detail"].lower()


async def test_tailor_resume_generates_and_saves_artifact(client):
    from app.db.mongo import db
    from app.schemas.artifact import TailoredArtifact

    await db.db.resume_snapshots.insert_one({
        "uid": "test-uid-12345",
        "firestoreResumeId": "abc",
        "version": 1,
        "structuredData": {"personalDetails": {"fullName": "Test User"}},
        "active": True,
    })

    fake_result = TailoredArtifact(tailoredResume='{"personalDetails": {"fullName": "Test User"}}', coverLetter=None)
    with patch("app.api.v1.tailor.gemini_client.generate_structured", new=AsyncMock(return_value=fake_result)):
        # Job ID intentionally shaped like a Firestore ID (not a valid Mongo ObjectId hex
        # string) -- regression guard for the ObjectId(job_id) bug found this session.
        resp = await client.post("/v1/tailor/ZzfXaN3aLROzXWkUcFD2?type=resume", json={"description": "JD text"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["tailoredResume"]["personalDetails"]["fullName"] == "Test User"
    assert body["data"]["coverLetter"] is None


async def test_tailor_cover_letter_type_is_sent_to_the_model(client):
    """Regression guard: the endpoint used to ignore ?type= entirely and always generate a
    resume-shaped response, even when the frontend asked for a cover letter."""
    from app.db.mongo import db
    from app.schemas.artifact import TailoredArtifact

    await db.db.resume_snapshots.insert_one({
        "uid": "test-uid-12345",
        "firestoreResumeId": "abc",
        "version": 1,
        "structuredData": {"personalDetails": {"fullName": "Test User"}},
        "active": True,
    })

    fake_result = TailoredArtifact(tailoredResume=None, coverLetter="Dear Hiring Manager,...")
    captured = {}

    async def capture_call(**kwargs):
        captured.update(kwargs)
        return fake_result

    with patch("app.api.v1.tailor.gemini_client.generate_structured", new=AsyncMock(side_effect=capture_call)):
        resp = await client.post("/v1/tailor/job1?type=coverLetter", json={"description": "JD text"})

    assert resp.status_code == 200
    assert resp.json()["data"]["coverLetter"] == "Dear Hiring Manager,..."
    assert "coverLetter" in captured["system"] or "cover letter" in captured["system"].lower()


async def test_tailor_requires_auth(client):
    from app.main import app
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    resp = await client.post("/v1/tailor/job1?type=resume", json={"description": "x"})
    assert resp.status_code in (401, 403)
