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
async def get_scouted_jobs(user: dict = Depends(get_current_user)):
    # Fetch all jobs from MongoDB
    cursor = db.db.job_postings.find({}).sort("discoveredAt", -1).limit(50)
    jobs = await cursor.to_list(length=50)
    for job in jobs:
        job["id"] = str(job["_id"])
        del job["_id"]
    return jobs
