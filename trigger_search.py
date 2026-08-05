import asyncio
from app.db.mongo import db
from app.worker import run_single_automation_task

async def run():
    await db.connect()
    # Find all automation settings and trigger a manual Celery search run for each
    cursor = db.db.automation_settings.find({})
    settings = await cursor.to_list(length=100)
    print(f"Found {len(settings)} user search settings.")
    for s in settings:
        print(f"Triggering search profile for user {s.get('uid')} - keyword: {s.get('jobTitles')}")
        run_single_automation_task.delay(str(s["_id"]))
    await db.close()

if __name__ == "__main__":
    asyncio.run(run())
