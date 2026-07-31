from fastapi import APIRouter, Depends, HTTPException
from ...connectors.greenhouse import GreenhouseConnector
from ...connectors.lever import LeverConnector
from ...worker import ingest_jobs_task
from ...auth import get_current_user
from ...db.mongo import db

router = APIRouter()

@router.post("/scout")
async def trigger_scout(source: str, token: str, user: dict = Depends(get_current_user)):
    if source == "greenhouse":
        connector = GreenhouseConnector(token)
    elif source == "lever":
        connector = LeverConnector(token)
    else:
        raise HTTPException(status_code=400, detail="Unsupported source")
    
    try:
        jobs = await connector.fetch_jobs()
        # Convert jobs to dict for Celery
        jobs_dict = [job.model_dump() for job in jobs]
        ingest_jobs_task.delay(jobs_dict)
        return {"status": "started", "count": len(jobs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jobs")
async def get_scouted_jobs(user: dict = Depends(get_current_user)):
    # Fetch all jobs from MongoDB
    cursor = db.db.job_postings.find({}).sort("discoveredAt", -1).limit(50)
    jobs = await cursor.to_list(length=50)
    for job in jobs:
        job["id"] = str(job["_id"])
        del job["_id"]
    return jobs
