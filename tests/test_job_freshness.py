from datetime import datetime, timedelta, timezone


async def test_upsert_preserves_first_discovered_timestamp(client):
    from app.db.mongo import db

    canonical = "freshness-regression-test"
    first = datetime.now(timezone.utc) - timedelta(days=10)
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        await db.upsert_job({
            "canonicalHash": canonical,
            "source": "manual",
            "sourceJobId": "1",
            "companyName": "Acme",
            "title": "Engineer",
            "descriptionText": "Role",
            "applyUrl": "https://example.com/job",
            "canonicalUrl": "https://example.com/job",
            "discoveredAt": first,
        })
        await db.upsert_job({
            "canonicalHash": canonical,
            "source": "manual",
            "sourceJobId": "1",
            "companyName": "Acme",
            "title": "Engineer",
            "descriptionText": "Updated role",
            "applyUrl": "https://example.com/job",
            "canonicalUrl": "https://example.com/job",
        })
        saved = await db.db.job_postings.find_one({"canonicalHash": canonical})
        # MongoDB BSON dates retain millisecond precision.
        expected_first = first.replace(microsecond=(first.microsecond // 1000) * 1000, tzinfo=None)
        assert saved["discoveredAt"] == expected_first
        assert saved["lastSeenAt"] > expected_first
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})
