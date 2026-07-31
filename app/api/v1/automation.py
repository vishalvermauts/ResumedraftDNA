from fastapi import APIRouter, Depends
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.automation import AutomationSettings
from datetime import datetime

router = APIRouter()

DEFAULTS = {"jobTitles": [], "locations": [], "remoteOnly": False, "salaryMin": None, "frequencyHours": 24, "enabled": False}

@router.post("/automation-settings")
async def save_automation_settings(settings: AutomationSettings, user: dict = Depends(get_current_user)):
    doc = settings.model_dump()
    doc["uid"] = user["uid"]
    doc["updatedAt"] = datetime.utcnow()

    await db.db.automation_settings.update_one(
        {"uid": user["uid"]},
        {"$set": doc},
        upsert=True
    )
    return {"status": "success"}

@router.get("/automation-settings")
async def get_automation_settings(user: dict = Depends(get_current_user)):
    doc = await db.db.automation_settings.find_one({"uid": user["uid"]})
    if not doc:
        return DEFAULTS
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc
