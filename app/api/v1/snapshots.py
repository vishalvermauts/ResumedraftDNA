from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.snapshot import ResumeSnapshot
import hashlib
import json
from datetime import datetime

router = APIRouter()

@router.post("/resume-snapshots")
async def create_resume_snapshot(
    snapshot: ResumeSnapshot,
    user: dict = Depends(get_current_user)
):
    # 1. Unset all existing active snapshots
    await db.db.resume_snapshots.update_many(
        {"uid": user["uid"], "active": True},
        {"$set": {"active": False}}
    )

    # 2. Create content hash
    content_str = json.dumps(snapshot.structuredData, sort_keys=True)
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()
    
    snapshot_doc = {
        "uid": user["uid"],
        "firestoreResumeId": snapshot.firestoreResumeId,
        "version": snapshot.version,
        "contentHash": content_hash,
        "structuredData": snapshot.structuredData,
        "active": True,
        "createdAt": datetime.utcnow()
    }
    
    result = await db.db.resume_snapshots.insert_one(snapshot_doc)
    return {"status": "success", "id": str(result.inserted_id)}

@router.post("/resume-snapshots/set-master")
async def set_master_resume(
    firestore_resume_id: str,
    user: dict = Depends(get_current_user)
):
    # 1. Unset all existing active snapshots for this user
    await db.db.resume_snapshots.update_many(
        {"uid": user["uid"], "active": True},
        {"$set": {"active": False}}
    )
    
    # 2. Set new master resume as active (lookup by firestoreResumeId)
    result = await db.db.resume_snapshots.update_one(
        {"uid": user["uid"], "firestoreResumeId": firestore_resume_id},
        {"$set": {"active": True}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Snapshot not found for this resume")
        
    return {"status": "success"}

@router.get("/resume-snapshots/active")
async def get_active_master_resume(user: dict = Depends(get_current_user)):
    snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not snapshot:
        raise HTTPException(status_code=404, detail="No active master resume found")
    snapshot["id"] = str(snapshot["_id"])
    del snapshot["_id"]
    return snapshot
