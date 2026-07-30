from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.watchlist import CompanyWatchlist
from bson import ObjectId
from datetime import datetime

router = APIRouter()

@router.post("/watchlist")
async def add_to_watchlist(
    item: CompanyWatchlist,
    user: dict = Depends(get_current_user)
):
    doc = item.model_dump()
    doc["uid"] = user["uid"]
    doc["createdAt"] = datetime.utcnow()
    doc["nextRunAt"] = datetime.utcnow()
    
    result = await db.db.company_watchlists.insert_one(doc)
    return {"status": "success", "id": str(result.inserted_id)}

@router.get("/watchlist")
async def get_watchlist(user: dict = Depends(get_current_user)):
    cursor = db.db.company_watchlists.find({"uid": user["uid"]})
    items = await cursor.to_list(length=100)
    for item in items:
        item["id"] = str(item["_id"])
        del item["_id"]
    return items

@router.delete("/watchlist/{item_id}")
async def delete_from_watchlist(item_id: str, user: dict = Depends(get_current_user)):
    result = await db.db.company_watchlists.delete_one({"_id": ObjectId(item_id), "uid": user["uid"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "success"}
