from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.snapshot import ResumeSnapshot
from ...ai.master_snapshot import add_source_provenance, content_hash
from datetime import datetime

router = APIRouter()

@router.post("/resume-snapshots")
async def create_resume_snapshot(
    snapshot: ResumeSnapshot,
    user: dict = Depends(get_current_user)
):
    structured_data = add_source_provenance(snapshot.structuredData)
    snapshot_hash = snapshot.contentHash or structured_data["metadata"]["contentHash"]
    source_file_hash = snapshot.sourceFileHash or structured_data.get("metadata", {}).get("sourceFileHash")
    # A content hash is the immutable identity of a snapshot.  If it already
    # exists, never replace its source data or timestamps; only select it.
    snapshot_doc = {
        "uid": user["uid"],
        "firestoreResumeId": snapshot.firestoreResumeId,
        "version": snapshot.version,
        "contentHash": snapshot_hash,
        "sourceFileHash": source_file_hash,
        "sourceTextHash": snapshot.sourceTextHash,
        "schemaVersion": snapshot.schemaVersion,
        "structuredData": structured_data,
        "active": False,
        "createdAt": datetime.utcnow()
    }
    existing = await db.db.resume_snapshots.find_one(
        {"uid": user["uid"], "contentHash": snapshot_hash}
    )
    if not existing:
        await db.db.resume_snapshots.insert_one(snapshot_doc)

    # Select only after the replacement is known to exist.  This avoids
    # leaving a user without a master when an invalid write is submitted.
    await db.db.resume_snapshots.update_many(
        {"uid": user["uid"], "active": True, "contentHash": {"$ne": snapshot_hash}},
        {"$set": {"active": False}}
    )
    await db.db.resume_snapshots.update_one(
        {"uid": user["uid"], "contentHash": snapshot_hash},
        {"$set": {"active": True}}
    )
    record = await db.db.resume_snapshots.find_one({"uid": user["uid"], "contentHash": snapshot_hash})
    return {"status": "success", "id": str(record["_id"]), "contentHash": snapshot_hash}

@router.post("/resume-snapshots/set-master")
async def set_master_resume(
    firestore_resume_id: str,
    user: dict = Depends(get_current_user)
):
    # Resolve the target before changing the active snapshot.
    result = await db.db.resume_snapshots.update_one(
        {"uid": user["uid"], "firestoreResumeId": firestore_resume_id},
        {"$set": {"active": False}}
    )
    
    # If the snapshot doesn't exist yet in Mongo, pull it dynamically from Firestore and seed it
    if result.matched_count == 0:
        import firebase_admin
        from firebase_admin import firestore
        try:
            # Get the initialized Firestore client safely
            fs = firestore.client()
        except ValueError:
            # If firebase_admin isn't initialized yet in this thread/module
            from ...auth import cred
            firebase_admin.initialize_app(cred, name="snapshots_fallback")
            fs = firestore.client()

        res_doc = fs.collection("resumes").document(firestore_resume_id).get()
        if not res_doc.exists:
            raise HTTPException(status_code=404, detail="Resume not found in Firestore")
        
        res_data = res_doc.to_dict()
        structured_data = add_source_provenance(res_data.get("data", {}), source_prefix="firestore")
        snapshot_content_hash = structured_data["metadata"]["contentHash"]
        
        snapshot_doc = {
            "uid": user["uid"],
            "firestoreResumeId": firestore_resume_id,
            "version": 1,
            "contentHash": snapshot_content_hash,
            "sourceFileHash": structured_data.get("metadata", {}).get("sourceFileHash"),
            "sourceTextHash": structured_data.get("metadata", {}).get("sourceTextHash"),
            "schemaVersion": structured_data.get("metadata", {}).get("schemaVersion", "resume-v1"),
            "structuredData": structured_data,
            "active": True,
            "createdAt": datetime.utcnow()
        }
        await db.db.resume_snapshots.insert_one(snapshot_doc)

    await db.db.resume_snapshots.update_many(
        {"uid": user["uid"], "active": True},
        {"$set": {"active": False}}
    )
    await db.db.resume_snapshots.update_one(
        {"uid": user["uid"], "firestoreResumeId": firestore_resume_id},
        {"$set": {"active": True}}
    )
        
    return {"status": "success"}

@router.get("/resume-snapshots/active")
async def get_active_master_resume(user: dict = Depends(get_current_user)):
    snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not snapshot:
        raise HTTPException(status_code=404, detail="No active master resume found")
    snapshot["id"] = str(snapshot["_id"])
    del snapshot["_id"]
    return snapshot
