from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...ai.gemini import gemini_client
from ...schemas.artifact import TailoredArtifact
from bson import ObjectId
from datetime import datetime

router = APIRouter()

@router.post("/tailor/{job_id}")
async def tailor_resume(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    # 1. Fetch job
    job = await db.db.job_postings.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # 2. Fetch master resume snapshot (active)
    resume_snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not resume_snapshot:
        raise HTTPException(status_code=404, detail="No active resume snapshot found")

    # 3. Generate tailored content
    system = """You are an expert recruiter and resume writer.
Your task is to take the provided Master Resume and create a Tailored Resume for the target Job Description (JD).

Follow these strict rules:
1. FILTERING: Review the Master Resume's certifications, projects, volunteer work, and experience. Include ONLY the items that are relevant to the provided Job Description (JD). If a project or volunteer section is not relevant, OMIT it from the output.
2. TAILORING: Rephrase existing experience bullet points to emphasize skills and achievements found in the JD. Use the JD's keywords.
3. STRUCTURE: Return ONLY valid JSON matching the schema for 'tailoredResume'.
"""
    
    # We must use json.dumps here to pass the dict as string
    import json
    prompt = f"MASTER RESUME:\n{json.dumps(resume_snapshot['structuredData'])}\n\nJOB DESCRIPTION:\n{job['descriptionText']}"
    
    result = await gemini_client.generate_structured(
        system=system,
        user=prompt,
        schema=TailoredArtifact
    )
    
    # 4. Save artifact
    artifact_doc = {
        "uid": user["uid"],
        "jobId": ObjectId(job_id),
        "type": "tailored_resume",
        "content": result.model_dump(),
        "createdAt": datetime.utcnow()
    }
    await db.db.artifacts.insert_one(artifact_doc)
    
    return {"status": "success", "data": result.model_dump()}
