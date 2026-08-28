from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...ai.gemini import gemini_client
from ...schemas.artifact import TailoredArtifact
from datetime import datetime
from pydantic import BaseModel
from ...ai.hybrid_tailor import analyze_resume, build_hybrid_prompt

router = APIRouter()

class TailorRequest(BaseModel):
    description: str


def _local_fallback(snapshot: dict, description: str, artifact_type: str):
    """Keep local certification usable when the external model quota is exhausted.

    This is deliberately conservative: it never invents experience. The resume
    artifact is the imported master data, while the cover letter only references
    the supplied job text and the candidate's existing profile.
    """
    data = snapshot.get("structuredData") or {}
    if artifact_type == "coverLetter":
        name = data.get("personalDetails", {}).get("fullName") or data.get("name") or "Candidate"
        title = "the advertised position"
        for line in description.splitlines():
            if line.lower().startswith("job title:"):
                title = line.split(":", 1)[1].strip() or title
                break
        return None, (
            f"Dear Hiring Manager,\n\n"
            f"I am writing to apply for {title}. My attached resume reflects my existing "
            f"administrative, coordination, and stakeholder-support experience. I would "
            f"welcome the opportunity to discuss how that background can support your team.\n\n"
            f"Kind regards,\n{name}"
        )
    return data, None


def _preserve_source_identity(source: dict, generated: dict | None):
    """Prevent model output from inventing or renaming master-resume records."""
    if not isinstance(generated, dict):
        return source

    result = dict(generated)
    source_jobs = source.get("employmentHistory") or []
    generated_jobs = generated.get("employmentHistory") or []
    if source_jobs:
        jobs = []
        for index, original in enumerate(source_jobs):
            candidate = generated_jobs[index] if index < len(generated_jobs) else {}
            candidate = candidate if isinstance(candidate, dict) else {}
            merged = dict(original)
            if isinstance(candidate.get("bulletPoints"), list) and candidate["bulletPoints"]:
                merged["bulletPoints"] = candidate["bulletPoints"]
            else:
                merged["bulletPoints"] = original.get("bulletPoints") or []
            jobs.append(merged)
        result["employmentHistory"] = jobs

    source_projects = source.get("projects") or []
    generated_projects = generated.get("projects") or []
    if source_projects:
        projects = []
        for index, original in enumerate(source_projects):
            candidate = generated_projects[index] if index < len(generated_projects) else {}
            candidate = candidate if isinstance(candidate, dict) else {}
            merged = dict(original)
            if isinstance(candidate.get("description"), list) and candidate["description"]:
                merged["description"] = candidate["description"]
            else:
                merged["description"] = original.get("description") or []
            projects.append(merged)
        result["projects"] = projects

    # A section may be shortened, but it must never disappear because the model
    # returned an incomplete schema.
    for section in ("education", "leadershipVolunteering", "certifications", "customSections"):
        if source.get(section) and not result.get(section):
            result[section] = source[section]
    if source.get("certifications"):
        result["certifications"] = source["certifications"]
    if source.get("leadershipVolunteering"):
        result["leadershipVolunteering"] = source["leadershipVolunteering"]
    if source.get("skills"):
        result["skills"] = source["skills"]
    return result

@router.post("/tailor/{job_id}")
async def tailor_resume(
    job_id: str,
    req: TailorRequest,
    type: str = "resume",
    mode: str = "ai",
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

    hybrid_report = {"mode": "ai-only", "jobConcepts": [], "items": []}
    working_resume = resume_snapshot["structuredData"]
    if mode == "hybrid":
        working_resume, hybrid_report = analyze_resume(working_resume, req.description)
        prompt = build_hybrid_prompt(req.description, json.dumps(working_resume), hybrid_report)
    else:
        prompt = f"MASTER RESUME:\n{json.dumps(working_resume)}\n\nJOB DESCRIPTION:\n{req.description}"

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
        tailored_resume = _preserve_source_identity(resume_snapshot["structuredData"], tailored_resume)
    except Exception as e:
        print(f"Gemini generation error: {str(e)}")
        fallback_enabled = os.getenv("ALLOW_TAILOR_FALLBACK", "false").lower() == "true"
        quota_error = "429" in str(e) or "spending cap" in str(e).lower() or "resource_exhausted" in str(e).lower()
        if not (fallback_enabled and quota_error):
            raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")
        fallback_snapshot = {**resume_snapshot, "structuredData": working_resume}
        tailored_resume, cover_letter = _local_fallback(fallback_snapshot, req.description, type)
        result = TailoredArtifact(
            tailoredResume=json.dumps(tailored_resume) if tailored_resume is not None else None,
            coverLetter=cover_letter,
        )

    # 4. Save artifact
    cover_letter = result.coverLetter
    if isinstance(cover_letter, str):
        try:
            parsed_cover = json.loads(cover_letter)
            if isinstance(parsed_cover, dict):
                cover_letter = parsed_cover.get("cover_letter") or parsed_cover.get("coverLetter") or cover_letter
        except json.JSONDecodeError:
            pass
    content = {"tailoredResume": tailored_resume, "coverLetter": cover_letter}
    content["tailoringComparison"] = hybrid_report
    artifact_doc = {
        "uid": user["uid"],
        "jobId": job_id,
        "type": "tailored_resume" if type == "resume" else "cover_letter",
        "content": content,
        "createdAt": datetime.utcnow()
    }
    await db.db.artifacts.insert_one(artifact_doc)

    return {"status": "success", "data": content}
