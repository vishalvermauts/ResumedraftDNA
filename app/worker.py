import os
import re
import json
import random
import inspect
import hashlib
from celery import Celery
from .db.mongo import db
from .connectors.registry import get_connector
from .connectors.base import (
    SUCCESS_WITH_JOBS,
    SUCCESS_EMPTY,
    NOT_SUPPORTED_OR_UNAVAILABLE,
    ERROR,
    ConnectorError,
    ConnectorBackoffError,
)
from .connectors.adzuna import search_by_keywords as adzuna_search_by_keywords
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import timedelta, datetime, timezone
from bson import ObjectId

_GREENHOUSE_URL_RE = re.compile(r'(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)')
_LEVER_URL_RE = re.compile(r'jobs\.lever\.co/([^/]+)/([a-f0-9-]{20,})')

# A provider that has been failing is demoted back to the full fallback chain once a
# resolvedConnectorType crosses this many consecutive failed runs.
RESOLUTION_FAILURE_THRESHOLD = 3

# Max seconds of random jitter added before each company's fetch within a run, so the
# top-of-hour run spreads its provider requests over a ramp instead of a tight burst.
JITTER_MAX_SECONDS = float(os.getenv("DISCOVER_JITTER_MAX_SECONDS", "240"))


def _fetch_with_status(loop, connector, etag, label):
    """Run one connector's fetch inside the task's legacy sync event-loop and return
    (jobs, status, etag_after). Reads the connector's `status` side-effect (set by the
    new plan-aware connectors) and falls back to inferring from the list length for the
    older connectors that only ever return a list. Raises ConnectorBackoffError on a
    429/5xx so the caller can back that provider off for the rest of the run."""
    try:
        params = inspect.signature(connector.fetch_jobs).parameters
        if "etag" in params:
            jobs = loop.run_until_complete(connector.fetch_jobs(etag=etag))
        else:
            jobs = loop.run_until_complete(connector.fetch_jobs())
    except ConnectorBackoffError:
        raise
    except Exception as exc:
        print(f"Error fetching ({label}): {exc}")
        return [], ERROR, getattr(connector, "etag", None)

    status = getattr(connector, "status", None)
    if status not in (SUCCESS_WITH_JOBS, SUCCESS_EMPTY, NOT_SUPPORTED_OR_UNAVAILABLE, ERROR):
        status = SUCCESS_WITH_JOBS if jobs else SUCCESS_EMPTY
    return jobs, status, getattr(connector, "etag", None)


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

    # Per-provider circuit breaker for the entire run: once a provider returns a
    # 429/5xx (ConnectorBackoffError), skip it for every remaining company in this
    # run rather than hammering it; the next hourly run retries it fresh.
    provider_backoff = set()
    now = datetime.now(timezone.utc)

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

        # Spread requests across the run so the top-of-hour doesn't fire every company's
        # fetch back-to-back in a tight synchronous burst.
        if JITTER_MAX_SECONDS > 0:
            loop.run_until_complete(asyncio.sleep(random.uniform(0.0, JITTER_MAX_SECONDS)))

        resolution = wl.get("resolved") or {}
        resolved_type = resolution.get("resolvedConnectorType")
        consecutive_failures = int(resolution.get("consecutiveFailures") or 0)
        resolved_etags = resolution.get("etags") or {}

        # Preferred order: if we already know a working provider for this company and it
        # hasn't recently started failing, try it first/only before re-walking the chain.
        if resolved_type and consecutive_failures < RESOLUTION_FAILURE_THRESHOLD:
            chain = [resolved_type] + [c for c in priority if c != resolved_type]
        else:
            chain = list(priority)

        jobs = []
        chosen_type = None
        chosen_status = None
        connector_etags = dict(resolved_etags)
        run_failed = False

        for c_type in chain:
            if c_type in provider_backoff:
                continue
            connector = get_connector(c_type, config)
            if not connector:
                continue
            try:
                jobs, status, etag_after = _fetch_with_status(
                    loop, connector, resolved_etags.get(c_type), label=c_type
                )
            except ConnectorBackoffError as exc:
                provider_backoff.add(c_type)
                run_failed = True
                print(f"Backing off ({c_type}) for {wl.get('companyName')}: {exc}")
                continue

            if etag_after:
                connector_etags[c_type] = etag_after

            if status == SUCCESS_WITH_JOBS:
                chosen_type = c_type
                chosen_status = status
                break
            if status == SUCCESS_EMPTY:
                # Provider genuinely answered with zero jobs for right now. Remember it
                # as a candidate so future runs prefer it, but keep walking the chain so
                # a richer source can still supply jobs for this company this run.
                if chosen_type is None:
                    chosen_type = c_type
                continue
            if status == NOT_SUPPORTED_OR_UNAVAILABLE:
                # This provider doesn't work for this company (plan/board absent); move on.
                # If it was our previously-resolved provider it stopped working, so count
                # it as a failure to eventually fall back to the full chain.
                if c_type == resolved_type:
                    run_failed = True
                continue
            # status == ERROR: the provider errored; treat as a failure, try the next one.
            run_failed = True
            continue

        if chosen_type and chosen_status == SUCCESS_WITH_JOBS:
            run_failed = False

        # --- Persist per-company resolution state -------------------------------
        new_failures = 0
        if run_failed:
            new_failures = consecutive_failures + 1

        resolved_doc = {
            # Which connector in the chain actually answered (with or without jobs).
            "resolvedConnectorType": chosen_type,
            # The exact config that worked -- mirrors the input config; kept separate so a
            # future discovery could store a corrected token if boardToken differs from
            # what the user entered.
            "resolvedConfig": config,
            # Last status from the fetched connector (success_with_jobs / success_empty /
            # not_supported_or_unavailable / error).
            "connectorStatus": chosen_status,
            # The last successful discovery (fires even for success_empty, which is a
            # healthy provider with no postings).
            "lastSuccessAt": now if chosen_status in (
                SUCCESS_WITH_JOBS, SUCCESS_EMPTY
            ) else resolution.get("lastSuccessAt"),
            # Consecutive failed runs of the resolved provider (used to trigger a re-walk
            # of the full fallback chain once this crosses RESOLUTION_FAILURE_THRESHOLD).
            "consecutiveFailures": new_failures,
            # Optional ETag per provider, for conditional requests when supported.
            "etags": connector_etags,
        }

        loop.run_until_complete(
            db.db.company_watchlists.update_one(
                {"_id": wl["_id"]},
                {"$set": {"resolved": resolved_doc, "lastCheckedAt": now}},
            )
        )

        if jobs:
            jobs_dict = [job.model_dump() for job in jobs]
            ingest_jobs_task.delay(jobs_dict)

    return "Discovery task completed"

_SPONSORSHIP_RE = re.compile(r'\bsponsor(ship)?\b|\bvisa\s+sponsor|\bwill\s+sponsor', re.IGNORECASE)


def _mentions_sponsorship(description: str) -> bool:
    """Heuristic, not a structured field -- none of the connectors (Adzuna included) expose
    visa sponsorship as a real filter, so this scans the description text every source
    already returns. Deliberately broad (matches "sponsor"/"sponsorship"/"visa sponsor"/"will
    sponsor") since postings phrase this inconsistently; false positives from an unrelated
    "sponsor" mention are possible but rare in job description text."""
    return bool(_SPONSORSHIP_RE.search(description or ""))


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

def _run_discovery_for_one(s, loop, fs, now, force=False):
    """Runs personalized discovery for a single automation_settings doc. Extracted from
    personalized_discovery_task so a manual "Run Now" trigger (run_single_automation_task) can
    execute the exact same matching logic for one record on demand, bypassing the frequency
    throttle via force=True."""
    titles = s.get("jobTitles") or []
    if not titles:
        return

    if not force:
        last_run = s.get("lastRunAt")
        freq_hours = s.get("frequencyHours", 24)
        if last_run:
            last_run_utc = last_run if last_run.tzinfo else last_run.replace(tzinfo=timezone.utc)
            if now - last_run_utc < timedelta(hours=freq_hours):
                return

    uid = s["uid"]
    locations = s.get("locations") or ["Remote"]

    existing_urls = {
        d.to_dict().get("url")
        for d in fs.collection("jobs").where("uid", "==", uid).stream()
    }

    # Which connectors may contribute matches -- empty means no restriction (every source),
    # which is also what a pre-existing doc without this field gets via `.get(...) or []`.
    sources = s.get("sources") or []
    source_allowed = (lambda src: not sources or src in sources)
    visa_only = s.get("visaSponsorshipOnly", False)

    # Handle country-wide filters (e.g., "Australia (All Locations)" matches any job in Australia)
    has_country_filters = False
    target_countries = []
    for loc in locations:
        if "all locations" in loc.lower():
            has_country_filters = True
            country_name = loc.split("(")[0].strip().lower()
            target_countries.append(country_name)

    def _save_job(*, title, company, location, description, url, source):
        if not url:
            return
        if visa_only and not _mentions_sponsorship(description):
            return
        
        # Check location constraints
        if locations and "remote" not in [l.lower() for l in locations]:
            matched_loc = False
            # Check country-level match (e.g., if Australia (All Locations) is selected, match 'au' or 'australia')
            if has_country_filters:
                loc_lower = str(location).lower()
                for c_name in target_countries:
                    # Match 'australia' or country abbreviation 'au'
                    if c_name in loc_lower or (c_name == "australia" and (" au" in loc_lower or ", au" in loc_lower or loc_lower == "au")):
                        matched_loc = True
                        break
            
            # Check city-level match
            if not matched_loc:
                for loc_str in locations:
                    city_part = loc_str.split(",")[0].strip().lower()
                    if city_part in str(location).lower():
                        matched_loc = True
                        break
            
            if not matched_loc and location:
                # Filter out this job as it is not in the user's targeted locations
                return

        canonical_hash = hashlib.sha256((url or f"{company}_{title}").encode()).hexdigest()
        job_doc = {
            "canonicalHash": canonical_hash,
            "title": title,
            "companyName": company,
            "location": [{"raw": location}],
            "descriptionText": description,
            "applyUrl": url,
            "canonicalUrl": url,
            "source": source,
            "discoveredAt": datetime.now(timezone.utc)
        }
        loop.run_until_complete(db.upsert_job(job_doc))

        # Mirror copy directly into Firestore 'jobs' collection for the user so it populates the AI Job Scout
        if url not in existing_urls:
            try:
                fs.collection("jobs").add({
                    "uid": uid,
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "description": description,
                    "source": source,
                    "foundVia": "scout",
                    "status": "saved",
                    "bookmarked": False,
                    "createdAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc),
                    "canonicalHash": canonical_hash
                })
                existing_urls.add(url)
            except Exception as fs_job_err:
                print(f"Automation: Failed to sync job to user Firestore collection: {fs_job_err}")

    title_query = {
        "$and": [
            {"$or": [{"title": {"$regex": re.escape(t), "$options": "i"}} for t in titles]},
            {"status": {"$ne": "expired"}}
        ]
    }
    if sources:
        title_query["$and"].append({"source": {"$in": sources}})
    corpus_matches = loop.run_until_complete(db.db.job_postings.find(title_query).to_list(length=30))
    for job in corpus_matches:
        # Extract location parsing dynamically to handle nested dicts and list structures
        raw_location = ""
        job_loc = job.get("location")
        if isinstance(job_loc, list) and len(job_loc) > 0:
            raw_location = job_loc[0].get("raw", "") if isinstance(job_loc[0], dict) else str(job_loc[0])
        elif isinstance(job_loc, dict):
            raw_location = job_loc.get("fullLocation") or job_loc.get("city") or job_loc.get("raw") or ""
        elif job_loc:
            raw_location = str(job_loc)

        _save_job(
            title=job.get("title", ""),
            company=job.get("companyName", ""),
            location=raw_location,
            description=job.get("descriptionText", ""),
            url=job.get("applyUrl") or job.get("canonicalUrl"),
            source=job.get("source", "unknown"),
        )

    # 2) Adzuna, queried live and directly by keyword -- unlike the ATS connectors above,
    #    Adzuna is a broad aggregator that can be searched by title/location on demand, not
    #    just pre-scraped per watched company, so this runs independently of the corpus step.
    if source_allowed("adzuna"):
        # Auto-detect country code from location strings, defaulting to US
        country = "us"
        locs_combined = " ".join(locations).lower()
        if "australia" in locs_combined or "nsw" in locs_combined or "vic" in locs_combined or "qld" in locs_combined or "wa" in locs_combined or "act" in locs_combined:
            country = "au"
        elif "united kingdom" in locs_combined or "london" in locs_combined or " uk" in locs_combined or "gb" in locs_combined:
            country = "gb"
        elif "canada" in locs_combined or " ca" in locs_combined:
            country = "ca"
        elif "germany" in locs_combined or " de" in locs_combined:
            country = "de"
        elif s.get("country"):
            country = s.get("country").lower()

        try:
            adzuna_jobs = loop.run_until_complete(adzuna_search_by_keywords(
                titles, locations=locations, country=country, remote_only=s.get("remoteOnly", False),
            ))
        except (ConnectorError, ConnectorBackoffError) as e:
            print(f"Automation: Adzuna search failed for {uid}: {e}")
            adzuna_jobs = []
        for job in adzuna_jobs:
            _save_job(
                title=job.title, company=job.companyName,
                location=job.location[0].raw if job.location else "",
                description=job.descriptionText, url=job.applyUrl, source="adzuna",
            )

    # 3) Gemini + Search grounding is permanently disabled.
    if source_allowed("ai_search"):
        print(f"Automation: ai_search source is disabled for uid={uid}; skipping web-wide fallback")

    loop.run_until_complete(
        db.db.automation_settings.update_one({"_id": s["_id"]}, {"$set": {"lastRunAt": now}})
    )
    # Sync back to Firestore so frontend UI shows updated runtime instead of "Never ran"
    try:
        firestore_id = s.get("firestoreId") or str(s["_id"])
        fs.collection("automation_settings").document(firestore_id).update({
            "lastRun": now.isoformat()
        })
    except Exception as fs_err:
        print(f"Automation: Failed to sync lastRun back to Firestore for settings {s.get('_id')}: {fs_err}")



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
        _run_discovery_for_one(s, loop, fs, now, force=False)

    return "Personalized discovery completed"


@celery_app.task
def run_single_automation_task(setting_id):
    """Manual "Run Now" trigger for one automation_settings record, queued from
    POST /automation-settings/{id}/run-now. Runs the same matching logic as the hourly beat
    job but for a single record and bypassing the frequency throttle."""
    loop = asyncio.get_event_loop()
    if db.db is None:
        loop.run_until_complete(db.connect())

    s = loop.run_until_complete(db.db.automation_settings.find_one({"_id": ObjectId(setting_id)}))
    if not s:
        return "Settings not found"

    fs = firestore.client()
    _run_discovery_for_one(s, loop, fs, datetime.now(timezone.utc), force=True)
    return "Manual run completed"
