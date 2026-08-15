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
    import os

    # Load system prompt rules dynamically from standalone Markdown files
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if type == "coverLetter":
        prompt_path = os.path.join(base_dir, "ai", "prompts", "cover_letter.md")
    else:
        prompt_path = os.path.join(base_dir, "ai", "prompts", "resume_tailor.md")

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system = f.read()
    except Exception as e:
        print(f"Failed to read prompt rules file at {prompt_path}: {e}")
        raise HTTPException(
            status_code=500, 
            detail="System prompt configuration missing or unreadable on backend."
        )

    prompt = f"MASTER RESUME:\n{json.dumps(resume_snapshot['structuredData'])}\n\nJOB DESCRIPTION:\n{req.description}"

    feature_label = "cover_letter" if type == "coverLetter" else "resume_tailor"
    try:
        result = await gemini_client.generate_structured(
            system=system,
            user=prompt,
            schema=TailoredArtifact,
            feature=feature_label,
            thinking_level="medium"
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
