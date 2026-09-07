from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.snapshot import ResumeSnapshot
from ...schemas.master_ingestion import MasterChunkExtraction, MasterSourceIngestRequest
from ...ai.master_snapshot import add_source_provenance, content_hash
from ...ai.master_ingestion import source_section_chunks
from ...ai.gemini import gemini_client
from datetime import datetime

router = APIRouter()


SECTION_INSTRUCTIONS = {
    "header": "Extract one personalDetails object and, if present, one professionalSummary string.",
    "employmentHistory": "Extract employment entries with jobTitle, company, location, startDate, endDate, and bulletPoints.",
    "education": "Extract education entries with degree, major, school, endDate, and relevantCoursework.",
    "projects": "Extract every project with name, techStack, url, and description as an array of source-supported bullets.",
    "skills": "Extract skills as category/items objects, preserving the source categories and exact skill names.",
    "leadershipVolunteering": "Extract every leadership or volunteering entry with role, organization, startDate, endDate, and bulletPoints.",
    "certifications": "Extract every certification with name and date.",
}


async def _extract_source_snapshot(request: MasterSourceIngestRequest) -> dict:
    # Keep each Vertex request bounded. Large projects/skills sections can be
    # syntactically valid but truncated JSON when sent as one request.
    chunks = source_section_chunks(request.rawText, max_lines=40)
    if not chunks:
        raise HTTPException(status_code=422, detail="Source text contains no extractable sections")
    result: dict = {
        "personalDetails": {},
        "professionalSummary": "",
        "employmentHistory": [],
        "education": [],
        "projects": [],
        "skills": [],
        "leadershipVolunteering": [],
        "certifications": [],
        "customSections": [],
    }
    for chunk in chunks:
        instruction = SECTION_INSTRUCTIONS.get(chunk["section"])
        if not instruction:
            continue
        prompt = (
            "Extract only facts present in this source chunk. Never invent, merge, rename, or upgrade facts. "
            "Return an object with an items array. " + instruction + "\n\n"
            f"SOURCE CHUNK {chunk['chunkId']} (lines {chunk['startLine']}-{chunk['endLine']}):\n{chunk['text']}"
        )
        try:
            extracted = await gemini_client.generate_structured(
                system=(
                    "You are a deterministic resume ingestion service. Return strict JSON only. "
                    "Every item must be directly supported by the supplied source chunk. "
                    "Use empty strings or arrays for unavailable fields."
                ),
                user=prompt,
                schema=MasterChunkExtraction,
                feature="resume_master_ingestion",
                max_output_tokens=8192,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Vertex master ingestion failed for {chunk['chunkId']}: {exc}",
            ) from exc
        if not extracted.items:
            continue
        for item in extracted.items:
            item["sourceEvidenceIds"] = [line["sourceId"] for line in chunk["lines"]]
        if chunk["section"] == "header":
            for item in extracted.items:
                if isinstance(item.get("personalDetails"), dict):
                    result["personalDetails"].update(item["personalDetails"])
                if item.get("professionalSummary"):
                    result["professionalSummary"] = item["professionalSummary"]
        else:
            result[chunk["section"]].extend(extracted.items)
    if not result["personalDetails"] and not result["employmentHistory"]:
        raise HTTPException(status_code=422, detail="Vertex extraction returned no usable master data")
    result["metadata"] = {
        "sourceFileName": request.sourceFileName,
        "sourceFormat": request.sourceFormat,
        "sourceFileHash": request.sourceFileHash,
        "sourceTextHash": request.sourceTextHash,
        "parseStatus": "validated",
        "ingestionMode": "vertex-section-chunks",
    }
    return add_source_provenance(result, source_prefix="source")


@router.post("/resume-snapshots/ingest-source")
async def ingest_source_resume(
    request: MasterSourceIngestRequest,
    user: dict = Depends(get_current_user),
):
    """Compile raw resume text once into a validated immutable master snapshot."""
    structured_data = await _extract_source_snapshot(request)
    snapshot_hash = structured_data["metadata"]["contentHash"]
    snapshot_doc = {
        "uid": user["uid"],
        "firestoreResumeId": None,
        "version": 1,
        "contentHash": snapshot_hash,
        "sourceFileHash": request.sourceFileHash,
        "sourceTextHash": request.sourceTextHash,
        "schemaVersion": "resume-v1",
        "structuredData": structured_data,
        "active": False,
        "createdAt": datetime.utcnow(),
    }
    existing = await db.db.resume_snapshots.find_one({"uid": user["uid"], "contentHash": snapshot_hash})
    if not existing:
        await db.db.resume_snapshots.insert_one(snapshot_doc)
    await db.db.resume_snapshots.update_many({"uid": user["uid"], "active": True}, {"$set": {"active": False}})
    await db.db.resume_snapshots.update_one(
        {"uid": user["uid"], "contentHash": snapshot_hash}, {"$set": {"active": True}}
    )
    return {"status": "success", "contentHash": snapshot_hash, "structuredData": structured_data}

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
