import os
from celery import Celery
from .db.mongo import db
from .connectors.registry import get_connector
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
