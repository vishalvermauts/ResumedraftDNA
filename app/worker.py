import os
import re
import json
from celery import Celery
from .db.mongo import db
from .connectors.registry import get_connector
from .ai.gemini import gemini_client
from .ai.quota import grounding_quota_available, record_grounding_usage
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import timedelta, datetime, timezone

_GREENHOUSE_URL_RE = re.compile(r'(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)')
_LEVER_URL_RE = re.compile(r'jobs\.lever\.co/([^/]+)/([a-f0-9-]{20,})')


def _upgrade_via_known_ats(apply_url, loop):
    """Gemini's web search can find a candidate posting anywhere, but it only ever writes
    back a short AI-written summary. If the URL it found happens to belong to a company on
    Greenhouse or Lever, fetch that company's real board and swap in the actual structured
    job (real description, verified apply link, correct source tag) instead of trusting the
    AI's guess. Returns a JobPosting or None if the URL isn't a recognized ATS, the board
    fetch fails, or the specific job can't be matched."""
    if not apply_url:
        return None

    m = _GREENHOUSE_URL_RE.search(apply_url)
    if m:
        token, job_id = m.group(1), m.group(2)
        connector = get_connector("greenhouse", {"boardToken": token})
        try:
            jobs = loop.run_until_complete(connector.fetch_jobs())
        except Exception:
            return None
        return next((j for j in jobs if j.sourceJobId == job_id), None)

    m = _LEVER_URL_RE.search(apply_url)
    if m:
        token = m.group(1)
        connector = get_connector("lever", {"boardToken": token})
        try:
            jobs = loop.run_until_complete(connector.fetch_jobs())
        except Exception:
            return None
        return next((j for j in jobs if j.applyUrl == apply_url), None)

    return None

if not firebase_admin._apps:
    firebase_admin.initialize_app(credentials.Certificate("serviceAccountKey.json"))

celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

celery_app.conf.beat_schedule = {
    'discover-jobs-every-hour': {
        'task': 'app.worker.discover_jobs_task',
        'schedule': timedelta(hours=1),
    },
    'personalized-discovery-every-hour': {
        'task': 'app.worker.personalized_discovery_task',
        'schedule': timedelta(hours=1),
    },
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task
def ingest_jobs_task(jobs_data):
    loop = asyncio.get_event_loop()
    if db.db is None:
        loop.run_until_complete(db.connect())
        
    for job in jobs_data:
        loop.run_until_complete(db.upsert_job(job))
    return f"Ingested {len(jobs_data)} jobs"

@celery_app.task
def discover_jobs_task():
    loop = asyncio.get_event_loop()
    if db.db is None:
        loop.run_until_complete(db.connect())
    
    # Fetch watchlists
    watchlists = loop.run_until_complete(db.db.company_watchlists.find({"enabled": True}).to_list(length=100))

    for wl in watchlists:
        connector_cfg = wl.get("connector", {})
        # Fallback chain: try each connector type in order, stop at the first one that
        # returns results. Cheapest/most reliable sources should be listed first.
        priority = connector_cfg.get("priority") or ([connector_cfg["type"]] if connector_cfg.get("type") else [])
        config = {
            "boardToken": connector_cfg.get("boardToken"),
            "companyName": wl.get("companyName"),
            "careersUrl": wl.get("careersUrl"),
        }

        jobs = []
        for c_type in priority:
            connector = get_connector(c_type, config)
            if not connector:
                continue
            try:
                jobs = loop.run_until_complete(connector.fetch_jobs())
                if jobs:
                    break
            except Exception as e:
                print(f"Error fetching ({c_type}) for {wl.get('companyName')}: {e}")

        if jobs:
            jobs_dict = [job.model_dump() for job in jobs]
            ingest_jobs_task.delay(jobs_dict)

    return "Discovery task completed"

def _parse_grounded_json(text):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []

@celery_app.task
def personalized_discovery_task():
    """Per-user role/location job search. Checks two sources: (1) the shared job_postings
    corpus that Watchlist's discover_jobs_task builds from real Greenhouse/Lever/JSON-LD
    scrapes, matched by title/location -- real, structured data; (2) Gemini + Search
    grounding as a web-wide fallback for roles no watched company has open. Respects each
    user's configured frequency and the shared free-tier grounding quota. Writes matches
    directly to the user's Firestore `jobs` collection (foundVia: 'automation'; `source`
    keeps its true origin -- 'greenhouse'/'lever'/'jsonld'/'ai_search' -- so the existing
    per-source quality badge in the UI stays accurate regardless of how a job was added).
    Gemini's own web-wide results additionally get checked against Greenhouse/Lever: if the
    URL it found belongs to a company on one of those, the real structured job is fetched and
    swapped in for the AI's summary."""
    loop = asyncio.get_event_loop()
    if db.db is None:
        loop.run_until_complete(db.connect())

    now = datetime.now(timezone.utc)
    settings_list = loop.run_until_complete(
        db.db.automation_settings.find({"enabled": True}).to_list(length=200)
    )

    fs = firestore.client()

    for s in settings_list:
        titles = s.get("jobTitles") or []
        if not titles:
            continue

        last_run = s.get("lastRunAt")
        freq_hours = s.get("frequencyHours", 24)
        if last_run:
            last_run_utc = last_run if last_run.tzinfo else last_run.replace(tzinfo=timezone.utc)
            if now - last_run_utc < timedelta(hours=freq_hours):
                continue

        uid = s["uid"]
        locations = s.get("locations") or ["Remote"]

        existing_urls = {
            d.to_dict().get("url")
            for d in fs.collection("jobs").where("uid", "==", uid).stream()
        }

        # 1) Real scraped data first: match the shared corpus built by Watchlist connectors.
        title_query = {"$or": [{"title": {"$regex": re.escape(t), "$options": "i"}} for t in titles]}
        corpus_matches = loop.run_until_complete(db.db.job_postings.find(title_query).to_list(length=30))
        for job in corpus_matches:
            apply_url = job.get("applyUrl") or job.get("canonicalUrl")
            if not apply_url or apply_url in existing_urls:
                continue
            fs.collection("jobs").add({
                "uid": uid,
                "title": job.get("title", ""),
                "company": job.get("companyName", ""),
                "location": (job.get("location") or [{}])[0].get("raw", "") if job.get("location") else "",
                "description": job.get("descriptionText", ""),
                "url": apply_url,
                "source": job.get("source", "unknown"),
                "foundVia": "automation",
                "status": "saved",
                "bookmarked": False,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
            existing_urls.add(apply_url)

        # 2) Web-wide fallback via Gemini + Search grounding, quota-guarded.
        if not loop.run_until_complete(grounding_quota_available()):
            print("Automation: grounding quota exhausted this month, skipping AI search fallback")
            loop.run_until_complete(
                db.db.automation_settings.update_one({"_id": s["_id"]}, {"$set": {"lastRunAt": now}})
            )
            continue

        remote_clause = "Remote positions only. " if s.get("remoteOnly") else ""
        prompt = f"""Search for current open job postings matching: {' or '.join(titles)}, in {' or '.join(locations)}.
{remote_clause}Return ONLY a raw JSON array, no markdown fences, no prose. Max 10 results.
Each item: {{"title": str, "company": str, "applyUrl": str, "location": str, "description": str}}. If none found, return []."""

        try:
            text = loop.run_until_complete(gemini_client.generate_grounded(prompt))
            loop.run_until_complete(record_grounding_usage())
        except Exception as e:
            print(f"Automation search failed for {uid}: {e}")
            loop.run_until_complete(
                db.db.automation_settings.update_one({"_id": s["_id"]}, {"$set": {"lastRunAt": now}})
            )
            continue

        listings = _parse_grounded_json(text)

        for item in listings:
            if not isinstance(item, dict):
                continue
            apply_url = item.get("applyUrl")
            title = item.get("title")
            if not apply_url or not title or apply_url in existing_urls:
                continue

            upgraded = _upgrade_via_known_ats(apply_url, loop)
            if upgraded:
                fs.collection("jobs").add({
                    "uid": uid,
                    "title": upgraded.title,
                    "company": upgraded.companyName,
                    "location": upgraded.location[0].raw if upgraded.location else "",
                    "description": upgraded.descriptionText,
                    "url": upgraded.applyUrl,
                    "source": upgraded.source,
                    "foundVia": "automation",
                    "status": "saved",
                    "bookmarked": False,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                })
                existing_urls.add(upgraded.applyUrl)
                continue

            fs.collection("jobs").add({
                "uid": uid,
                "title": title,
                "company": item.get("company", ""),
                "location": item.get("location", ""),
                "description": item.get("description", ""),
                "url": apply_url,
                "source": "ai_search",
                "foundVia": "automation",
                "status": "saved",
                "bookmarked": False,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
            existing_urls.add(apply_url)

        loop.run_until_complete(
            db.db.automation_settings.update_one({"_id": s["_id"]}, {"$set": {"lastRunAt": now}})
        )

    return "Personalized discovery completed"
