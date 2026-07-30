import os
from celery import Celery
from .db.mongo import db
from .connectors.greenhouse import GreenhouseConnector
from .connectors.lever import LeverConnector
import asyncio
from datetime import timedelta

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
    if not db.db:
        loop.run_until_complete(db.connect())
        
    for job in jobs_data:
        loop.run_until_complete(db.upsert_job(job))
    return f"Ingested {len(jobs_data)} jobs"

@celery_app.task
def discover_jobs_task():
    loop = asyncio.get_event_loop()
    if not db.db:
        loop.run_until_complete(db.connect())
    
    # Fetch watchlists
    watchlists = loop.run_until_complete(db.db.company_watchlists.find({"enabled": True}).to_list(length=100))
    
    for wl in watchlists:
        c_type = wl.get("connector", {}).get("type")
        token = wl.get("connector", {}).get("boardToken")
        
        connector = None
        if c_type == "greenhouse":
            connector = GreenhouseConnector(token)
        elif c_type == "lever":
            connector = LeverConnector(token)
            
        if connector:
            try:
                jobs = loop.run_until_complete(connector.fetch_jobs())
                jobs_dict = [job.model_dump() for job in jobs]
                ingest_jobs_task.delay(jobs_dict)
            except Exception as e:
                print(f"Error fetching for {wl['companyName']}: {e}")
                
    return "Discovery task completed"
