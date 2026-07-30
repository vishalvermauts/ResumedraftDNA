import os
from celery import Celery
from .db.mongo import db
import asyncio

celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

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
        # Simple hack to ensure DB is connected in the worker process
        loop.run_until_complete(db.connect())
        
    for job in jobs_data:
        loop.run_until_complete(db.upsert_job(job))
    return f"Ingested {len(jobs_data)} jobs"
