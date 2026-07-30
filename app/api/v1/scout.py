from fastapi import APIRouter, HTTPException, BackgroundTasks
from ...connectors.greenhouse import GreenhouseConnector
from ...connectors.lever import LeverConnector
from ...worker import ingest_jobs_task

router = APIRouter()

@router.post("/scout")
async def trigger_scout(source: str, token: str, background_tasks: BackgroundTasks):
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
