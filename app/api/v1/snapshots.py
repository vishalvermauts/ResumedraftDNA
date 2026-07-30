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
    # Create content hash to avoid duplicate storage
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
    
    # In a real app, you'd check if this version already exists
    # For now, we insert.
    result = await db.db.resume_snapshots.insert_one(snapshot_doc)
    
    return {"status": "success", "id": str(result.inserted_id)}
