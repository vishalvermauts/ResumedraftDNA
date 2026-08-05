from fastapi import APIRouter, Depends, HTTPException
from ...connectors.registry import get_connector
from ...worker import ingest_jobs_task
from ...auth import get_current_user
from ...db.mongo import db

router = APIRouter()

@router.post("/scout")
async def trigger_scout(source: str, token: str, user: dict = Depends(get_current_user)):
    connector = get_connector(source, {"boardToken": token, "companyName": token, "careersUrl": None})
    if not connector:
        raise HTTPException(status_code=400, detail="Unsupported source")

    try:
        jobs = await connector.fetch_jobs()
        # Convert jobs to dict for Celery
        jobs_dict = [job.model_dump() for job in jobs]
        ingest_jobs_task.delay(jobs_dict)
        return {"status": "started", "count": len(jobs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/scout/watchlist")
async def trigger_watchlist_scout(user: dict = Depends(get_current_user)):
    """Runs real discovery now for the calling user's own watchlist companies (same connector
    priority chain as the hourly discover_jobs_task beat job), instead of the old /scout test
    endpoint which only ever exercised a single hardcoded Greenhouse board."""
    uid = user.get("uid")
    watchlists = await db.db.company_watchlists.find({"uid": uid, "enabled": True}).to_list(length=100)
    if not watchlists:
        # Auto-sync from Firestore if MongoDB watchlists are missing (e.g. database reset)
        try:
            from firebase_admin import firestore
            from datetime import datetime
            fs = firestore.client()
            fs_docs = fs.collection("company_watchlist").where("uid", "==", uid).where("active", "==", True).stream()
            for doc in fs_docs:
                data = doc.to_dict()
                wl_doc = {
                    "companyName": data.get("companyName"),
                    "careersUrl": data.get("careersUrl"),
                    "connector": {
                        "type": data.get("connectorType"),
                        "boardToken": data.get("boardToken"),
                        "priority": data.get("priority") or [data.get("connectorType"), "jsonld", "ai_search"],
                        "configuration": {}
                    },
                    "pollingFrequencyMinutes": 720,
                    "enabled": True,
                    "uid": uid,
                    "createdAt": datetime.utcnow(),
                    "nextRunAt": datetime.utcnow()
                }
                result = await db.db.company_watchlists.insert_one(wl_doc)
                doc.reference.update({"mongoId": str(result.inserted_id)})
            
            # Re-fetch from MongoDB
            watchlists = await db.db.company_watchlists.find({"uid": uid, "enabled": True}).to_list(length=100)
        except Exception as sync_err:
            print(f"Scout: Watchlist auto-sync from Firestore failed: {sync_err}")

    if not watchlists:
        raise HTTPException(status_code=400, detail="No companies on your watchlist yet -- add one first.")

    total = 0
    per_company = []
    for wl in watchlists:
        connector_cfg = wl.get("connector", {})
        priority = connector_cfg.get("priority") or ([connector_cfg["type"]] if connector_cfg.get("type") else [])
        config = {
            "boardToken": connector_cfg.get("boardToken"),
            "companyName": wl.get("companyName"),
            "careersUrl": wl.get("careersUrl"),
        }

        jobs = []
        used_connector = None
        for c_type in priority:
            connector = get_connector(c_type, config)
            if not connector:
                continue
            try:
                jobs = await connector.fetch_jobs()
                if jobs:
                    used_connector = c_type
                    break
            except Exception as e:
                print(f"Error fetching ({c_type}) for {wl.get('companyName')}: {e}")

        if jobs:
            jobs_dict = [job.model_dump() for job in jobs]
            ingest_jobs_task.delay(jobs_dict)
            total += len(jobs)
        per_company.append({"companyName": wl.get("companyName"), "count": len(jobs), "connector": used_connector})

    return {"status": "started", "count": total, "companies": per_company}

@router.get("/jobs")
async def get_scouted_jobs(personalized: bool = False, user: dict = Depends(get_current_user)):
    query_filter = {}
    uid = user.get("uid")

    if personalized and uid:
        # Fetch user's active automation settings
        settings = await db.db.automation_settings.find_one({"uid": uid})
        if settings:
            and_clauses = []
            
            # 1. Match job titles
            titles = settings.get("jobTitles") or []
            if titles:
                title_regexes = [{"title": {"$regex": t, "$options": "i"}} for t in titles if t]
                if title_regexes:
                    and_clauses.append({"$or": title_regexes})
            
            # 2. Match locations
            locations = settings.get("locations") or []
            if locations:
                loc_regexes = []
                for loc in locations:
                    if not loc:
                        continue
                    # Strip country/state suffix to match city name broadly (e.g. "Sydney" matches "Sydney, Australia")
                    city = loc.split(",")[0].strip()
                    loc_regexes.append({"location.raw": {"$regex": city, "$options": "i"}})
                    loc_regexes.append({"location": {"$regex": city, "$options": "i"}})
                if loc_regexes:
                    and_clauses.append({"$or": loc_regexes})

            if and_clauses:
                query_filter = {"$and": and_clauses}
            else:
                return []
        else:
            return []

    # Fetch jobs from MongoDB
    cursor = db.db.job_postings.find(query_filter).sort("discoveredAt", -1).limit(100)
    jobs = await cursor.to_list(length=100)
    for job in jobs:
        job["id"] = str(job["_id"])
        del job["_id"]
    return jobs
