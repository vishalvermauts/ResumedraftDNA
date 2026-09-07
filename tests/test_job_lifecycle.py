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


async def test_source_confirmed_close_marks_only_matching_job_filled(client):
    from app.db.mongo import db

    canonical = "filled-regression-test"
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        await db.upsert_job({
            "canonicalHash": canonical, "source": "recruitee", "sourceJobId": "closed-1",
            "companyName": "Acme", "title": "Engineer", "descriptionText": "Role",
            "applyUrl": "https://example.com/job", "canonicalUrl": "https://example.com/job",
        })
        await db.mark_source_closed("Acme", "recruitee", ["closed-1"], datetime.now(timezone.utc))
        saved = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert saved["status"] == "filled"
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})


async def test_passed_deadline_marks_job_expired_but_not_filled(client):
    from app.db.mongo import db

    canonical = "deadline-regression-test"
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        await db.upsert_job({
            "canonicalHash": canonical, "source": "jsonld", "sourceJobId": "deadline-1",
            "companyName": "Acme", "title": "Engineer", "descriptionText": "Role",
            "applyUrl": "https://example.com/job", "canonicalUrl": "https://example.com/job",
            "applicationDeadline": datetime.now(timezone.utc),
        })
        await db.expire_deadline_jobs(datetime.now(timezone.utc))
        saved = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert saved["status"] == "expired"
        assert saved["status"] != "filled"
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})


async def test_job_upsert_assigns_stable_company_id(client):
    from app.db.mongo import db

    canonical = "company-link-regression-test"
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        await db.upsert_job({
            "canonicalHash": canonical, "source": "jsonld", "sourceJobId": "link-1",
            "companyName": "Acme & Sons, Pty. Ltd.", "title": "Engineer",
            "descriptionText": "Role", "applyUrl": "https://example.com/job",
            "canonicalUrl": "https://example.com/job",
        })
        saved = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert saved["companyId"] == "acme-sons-pty-ltd"
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})


async def test_job_upsert_uses_posted_time_for_real_freshness(client):
    from app.db.mongo import db

    canonical = "freshness-regression-test"
    await db.db.job_postings.delete_one({"canonicalHash": canonical})
    try:
        posted = datetime(2026, 1, 5, tzinfo=timezone.utc)
        discovered = datetime(2026, 2, 5, tzinfo=timezone.utc)
        await db.upsert_job({
            "canonicalHash": canonical, "source": "jsonld", "sourceJobId": "fresh-1",
            "companyName": "Acme", "title": "Engineer", "descriptionText": "Role",
            "applyUrl": "https://example.com/job", "canonicalUrl": "https://example.com/job",
            "postedAt": posted, "discoveredAt": discovered,
        })
        saved = await db.db.job_postings.find_one({"canonicalHash": canonical})
        assert saved["freshnessAt"] == posted.replace(tzinfo=None)
    finally:
        await db.db.job_postings.delete_one({"canonicalHash": canonical})
