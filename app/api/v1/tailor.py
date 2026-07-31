from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...ai.gemini import gemini_client
from ...schemas.artifact import TailoredArtifact
from bson import ObjectId
from datetime import datetime

router = APIRouter()

from pydantic import BaseModel

class TailorRequest(BaseModel):
    description: str

@router.post("/tailor/{job_id}")
async def tailor_resume(
    job_id: str,
    req: TailorRequest,
    user: dict = Depends(get_current_user)
):
    # Fetch active resume snapshot
    resume_snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not resume_snapshot:
        raise HTTPException(status_code=404, detail="No active resume snapshot found")

    # Generate tailored content
    system = """You are an expert recruiter and resume writer.
Your task is to take the provided Master Resume and create a Tailored Resume for the target Job Description (JD).
Follow these strict rules:
1. FILTERING: Review the Master Resume's certifications, projects, volunteer work, and experience. Include ONLY the items that are relevant to the provided Job Description (JD).
2. TAILORING: Rephrase existing experience bullet points to emphasize skills and achievements found in the JD. Use the JD's keywords.
3. STRUCTURE: Return ONLY valid JSON matching the schema for 'tailoredResume'."""
    
    import json
    prompt = f"MASTER RESUME:\n{json.dumps(resume_snapshot['structuredData'])}\n\nJOB DESCRIPTION:\n{req.description}"
    
    result = await gemini_client.generate_structured(
        system=system,
        user=prompt,
        schema=TailoredArtifact
    )
    
    return {"status": "success", "data": result.model_dump()}
