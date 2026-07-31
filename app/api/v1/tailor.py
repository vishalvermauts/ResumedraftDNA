from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...ai.gemini import gemini_client
from ...schemas.artifact import TailoredArtifact
from datetime import datetime
from pydantic import BaseModel

router = APIRouter()

class TailorRequest(BaseModel):
    description: str

@router.post("/tailor/{job_id}")
async def tailor_resume(
    job_id: str,
    req: TailorRequest,
    type: str = "resume",
    user: dict = Depends(get_current_user)
):
    # Fetch active resume snapshot
    resume_snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not resume_snapshot:
        raise HTTPException(status_code=404, detail="No active resume snapshot found")

    import json

    if type == "coverLetter":
        system = """You are an expert recruiter and career coach.
Write a compelling, personalized cover letter for the candidate (described by the Master Resume) applying to the target Job Description (JD).
Use the JD's keywords and tone. Keep it concise (3-4 paragraphs).
Return ONLY valid JSON. The 'coverLetter' field must contain the full cover letter text as a plain string. Leave 'tailoredResume' null."""
    else:
        system = """You are an expert recruiter and resume writer.
Your task is to take the provided Master Resume and create a Tailored Resume for the target Job Description (JD).
Follow these strict rules:
1. FILTERING: Review the Master Resume's certifications, projects, volunteer work, and experience. Include ONLY the items that are relevant to the provided Job Description (JD). If a project or volunteer section is not relevant, OMIT it from the output.
2. TAILORING: Rephrase existing experience bullet points to emphasize skills and achievements found in the JD. Use the JD's keywords.
3. STRUCTURE: Return ONLY valid JSON. The 'tailoredResume' field must be a JSON-encoded STRING containing an object with the exact same shape as the Master Resume. Leave 'coverLetter' null."""

    prompt = f"MASTER RESUME:\n{json.dumps(resume_snapshot['structuredData'])}\n\nJOB DESCRIPTION:\n{req.description}"

    try:
        result = await gemini_client.generate_structured(
            system=system,
            user=prompt,
            schema=TailoredArtifact
        )
        tailored_resume = json.loads(result.tailoredResume) if result.tailoredResume else None
    except Exception as e:
        print(f"Gemini generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")

    # 4. Save artifact
    content = {"tailoredResume": tailored_resume, "coverLetter": result.coverLetter}
    artifact_doc = {
        "uid": user["uid"],
        "jobId": job_id,
        "type": "tailored_resume" if type == "resume" else "cover_letter",
        "content": content,
        "createdAt": datetime.utcnow()
    }
    await db.db.artifacts.insert_one(artifact_doc)

    return {"status": "success", "data": content}
