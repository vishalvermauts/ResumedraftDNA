from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from bson.errors import InvalidId
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.automation import AutomationSettings
from ...worker import run_single_automation_task
from datetime import datetime

router = APIRouter()


def _serialize(doc):
    doc["id"] = str(doc.pop("_id"))
    if doc.get("lastRunAt"):
        doc["lastRunAt"] = doc["lastRunAt"].isoformat()
    if doc.get("updatedAt"):
        doc["updatedAt"] = doc["updatedAt"].isoformat()
    return doc


async def _find_owned(setting_id, uid):
    try:
        oid = ObjectId(setting_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Automation search not found")
    doc = await db.db.automation_settings.find_one({"_id": oid, "uid": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Automation search not found")
    return doc


@router.get("/automation-settings")
async def list_automation_settings(user: dict = Depends(get_current_user)):
    """Each user can run several independent role/location searches -- one automation_settings
    doc per card. A legacy pre-multi-role account just has a single doc here, which renders as
    one card, so no migration is needed."""
    docs = await db.db.automation_settings.find({"uid": user["uid"]}).to_list(length=50)
    return [_serialize(d) for d in docs]


@router.post("/automation-settings")
async def create_automation_settings(settings: AutomationSettings, user: dict = Depends(get_current_user)):
    doc = settings.model_dump()
    doc["uid"] = user["uid"]
    doc["updatedAt"] = datetime.utcnow()
    result = await db.db.automation_settings.insert_one(doc)
    return {"status": "success", "id": str(result.inserted_id)}


@router.put("/automation-settings/{setting_id}")
async def update_automation_settings(setting_id: str, settings: AutomationSettings, user: dict = Depends(get_current_user)):
    await _find_owned(setting_id, user["uid"])
    doc = settings.model_dump()
    doc["updatedAt"] = datetime.utcnow()
    await db.db.automation_settings.update_one({"_id": ObjectId(setting_id)}, {"$set": doc})
    return {"status": "success"}


@router.delete("/automation-settings/{setting_id}")
async def delete_automation_settings(setting_id: str, user: dict = Depends(get_current_user)):
    await _find_owned(setting_id, user["uid"])
    await db.db.automation_settings.delete_one({"_id": ObjectId(setting_id)})
    return {"status": "success"}


@router.post("/automation-settings/{setting_id}/run-now")
async def run_automation_now(setting_id: str, user: dict = Depends(get_current_user)):
    """Manually triggers just this one automation search instead of waiting for its next
    scheduled run. Follows the same fire-and-forget Celery dispatch pattern as
    POST /scout/watchlist."""
    await _find_owned(setting_id, user["uid"])
    run_single_automation_task.delay(setting_id)
    return {"status": "started"}
