from datetime import datetime, timezone


async def test_healthy_empty_source_marks_jobs_stale_not_filled(client):
    from app.db.mongo import db

    canonical = "stale-regression-test"
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        base = {
            "canonicalHash": canonical,
            "source": "jsonld",
            "sourceJobId": "closed-role",
            "companyName": "Acme",
            "title": "Engineer",
            "descriptionText": "Role",
            "applyUrl": "https://example.com/job",
            "canonicalUrl": "https://example.com/job",
        }
        await db.upsert_job(base.copy())
        now = datetime.now(timezone.utc)
        await db.mark_source_empty("Acme", "jsonld", now)
        first = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert first["status"] == "active"
        assert first["missedPolls"] == 1
        await db.mark_source_empty("Acme", "jsonld", now)
        stale = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert stale["status"] == "stale"
        assert stale["missedPolls"] == 2
        assert stale["status"] != "filled"
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})
