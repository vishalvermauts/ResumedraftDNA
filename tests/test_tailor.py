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


async def test_hybrid_mode_sends_ranked_evidence_and_labels_response(client):
    from app.db.mongo import db
    from app.schemas.artifact import TailoredArtifact

    await db.db.resume_snapshots.insert_one({
        "uid": "test-uid-12345",
        "firestoreResumeId": "hybrid-test",
        "version": 1,
        "structuredData": {
            "personalDetails": {"fullName": "Test User"},
            "employmentHistory": [{
                "jobTitle": "Operations Coordinator",
                "bulletPoints": ["Coordinated transport for offshore personnel"],
            }],
            "projects": [{"title": "Offshore transport", "description": "Transport logistics"}],
        },
        "active": True,
    })

    captured = {}

    async def capture_call(**kwargs):
        captured.update(kwargs)
        return TailoredArtifact(
            tailoredResume='{"personalDetails": {"fullName": "Test User"}}',
            coverLetter=None,
        )

    with patch("app.api.v1.tailor.gemini_client.generate_structured", new=AsyncMock(side_effect=capture_call)):
        resp = await client.post(
            "/v1/tailor/hybrid-job?type=resume&mode=hybrid",
            json={"description": "Executive Assistant responsible for travel logistics"},
        )

    assert resp.status_code == 200
    assert "RANKING REPORT" in captured["user"]
    comparison = resp.json()["data"]["tailoringComparison"]
    assert comparison["mode"] == "hybrid-experimental"
    assert any(item["type"] == "experience-bullet" for item in comparison["items"])


def test_tailor_preserves_source_job_identity_and_sections():
    from app.api.v1.tailor import _preserve_source_identity

    source = {
        "employmentHistory": [{
            "jobTitle": "Rig Administrator & Logistics Officer",
            "company": "Dubai Petroleum",
            "startDate": "06/2018",
            "endDate": "01/2024",
            "bulletPoints": ["Coordinated transport for offshore personnel."],
        }],
        "education": [{"degree": "Master of Information Technology", "school": "UTS"}],
        "projects": [{"name": "StructZero", "description": ["Built an engineering platform."]}],
    }
    generated = {
        "employmentHistory": [{
            "jobTitle": "Senior Operations Manager",
            "company": "Invented Employer",
            "bulletPoints": ["Rewritten truthful bullet."],
        }],
        "projects": [{"name": "Invented Project", "description": ["Rewritten project."]}],
        "education": [],
    }

    result = _preserve_source_identity(source, generated)
    assert result["employmentHistory"][0]["jobTitle"] == "Rig Administrator & Logistics Officer"
    assert result["employmentHistory"][0]["company"] == "Dubai Petroleum"
    assert result["projects"][0]["name"] == "StructZero"
    assert result["education"] == source["education"]


async def test_tailor_requires_auth(client):
    from app.main import app
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    resp = await client.post("/v1/tailor/job1?type=resume", json={"description": "x"})
    assert resp.status_code in (401, 403)
