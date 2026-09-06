from fastapi import APIRouter, Depends, HTTPException
from ...auth import get_current_user
from ...db.mongo import db
from ...ai.gemini import gemini_client
from ...schemas.artifact import TailoredArtifact
from datetime import datetime
from pydantic import BaseModel
from ...ai.hybrid_tailor import analyze_resume, build_hybrid_prompt
from ...ai.validation import (
    ArtifactValidationError,
    validate_cover_letter,
    validate_protected_facts,
    validate_source_backed_sections,
)
from ...ai.master_snapshot import add_source_provenance
from firebase_admin import firestore
import re
import json
import os

router = APIRouter()


def _firestore_master_lookup_enabled() -> bool:
    """Only use the repair lookup when a Firestore target is explicitly configured."""
    return bool(os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("ENABLE_FIRESTORE_LOOKUP", "false").lower() == "true")

def _enforce_cover_letter_word_limit(text: str | None, maximum: int = 350):
    if not isinstance(text, str) or len(text.split()) <= maximum:
        return text
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    while len(' '.join(sentences).split()) > maximum and len(sentences) > 1:
        sentences.pop(min(range(len(sentences)), key=lambda index: len(sentences[index].split())))
    return ' '.join(sentences).split()[:maximum] and ' '.join(' '.join(sentences).split()[:maximum])

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


def _parse_model_json(value: str):
    """Accept a JSON object wrapped in harmless model prose, but not invalid JSON."""
    text = (value or '').strip().removeprefix('```json').removeprefix('```').strip()
    # Models occasionally emit raw control bytes inside JSON strings. They are
    # invalid JSON and have no useful semantic content in a resume artifact.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(text)
    if not isinstance(parsed, dict):
        raise ValueError('Model returned a non-object tailored resume')
    return parsed


def _preserve_source_identity(source: dict, generated: dict | None, description: str = ''):
    """Prevent model output from inventing or renaming master-resume records."""
    if not isinstance(generated, dict):
        return source

    result = dict(generated)
    source_jobs = source.get("employmentHistory") or []
    generated_jobs = generated.get("employmentHistory") or []
    if source_jobs:
        jobs = []
        # If the model returns an empty list, retain a bounded, deterministic
        # evidence set rather than either dropping all experience or copying
        # the entire master into a multi-page artifact.
        if not generated_jobs:
            jd_tokens = _relevance_tokens(description)
            ranked = sorted(
                source_jobs,
                key=lambda item: len(_relevance_tokens(json.dumps(item)) & jd_tokens),
                reverse=True,
            )[:3]
            result["employmentHistory"] = [
                {**item, "bulletPoints": (item.get("bulletPoints") or [])[:5]}
                for item in ranked
            ]
        else:
            for index, original in enumerate(source_jobs):
                candidate = next((item for item in generated_jobs
                                  if isinstance(item, dict) and original.get("id")
                                  and item.get("id") == original.get("id")), None)
                if candidate is None:
                    candidate = next((item for item in generated_jobs
                                      if isinstance(item, dict)
                                      and item.get("company") == original.get("company")
                                      and item.get("jobTitle") == original.get("jobTitle")), None)
                if candidate is None:
                    continue
                candidate = candidate if isinstance(candidate, dict) else {}
                merged = dict(original)
                if isinstance(candidate.get("bulletPoints"), list) and candidate["bulletPoints"]:
                    merged["bulletPoints"] = candidate["bulletPoints"]
                else:
                    merged["bulletPoints"] = original.get("bulletPoints") or []
                jobs.append(merged)
            if not jobs:
                jd_tokens = _relevance_tokens(description)
                ranked = sorted(
                    source_jobs,
                    key=lambda item: len(_relevance_tokens(json.dumps(item)) & jd_tokens),
                    reverse=True,
                )[:3]
                jobs = [
                    {**item, "bulletPoints": (item.get("bulletPoints") or [])[:5]}
                    for item in ranked
                ]
            result["employmentHistory"] = jobs

    source_projects = source.get("projects") or []
    generated_projects = generated.get("projects") or []
    if source_projects:
        projects = []
        for index, original in enumerate(source_projects):
            candidate = next((item for item in generated_projects
                              if isinstance(item, dict) and original.get("id")
                              and item.get("id") == original.get("id")), None)
            if candidate is None:
                candidate = next((item for item in generated_projects
                                  if isinstance(item, dict)
                                  and item.get("name") == original.get("name")), None)
            if candidate is None:
                continue
            candidate = candidate if isinstance(candidate, dict) else {}
            merged = dict(original)
            if isinstance(candidate.get("description"), list) and candidate["description"]:
                merged["description"] = candidate["description"]
            else:
                merged["description"] = original.get("description") or []
            projects.append(merged)
        if not projects and generated_projects:
            projects = [
                {**item, "description": (item.get("description") or [])[:3]}
                for item in source_projects[:2]
            ]
        result["projects"] = projects

    # The master remains complete in its own snapshot. A tailored artifact must
    # retain identity fields while allowing the model to select relevant skills,
    # projects, certifications, and leadership records.
    if source.get("education") and not result.get("education"):
        result["education"] = source["education"]
    return result


def _relevance_tokens(text: str):
    stop = {"the", "and", "for", "with", "from", "that", "this", "you", "will", "your", "are", "into", "only", "have"}
    return {word for word in re.findall(r"[a-z0-9]+", (text or '').lower()) if len(word) > 3 and word not in stop}


def _filter_selected_sections(source: dict, generated: dict, description: str):
    """Keep only source-backed optional records with real JD vocabulary overlap."""
    jd_tokens = _relevance_tokens(description)
    culture_signal = bool(jd_tokens & {
        "collaboration", "collaborative", "culture", "community", "stakeholder",
        "engagement", "inclusive", "team", "events", "leadership", "volunteer",
    })
    for section, limit in (("projects", 2), ("leadershipVolunteering", 3), ("certifications", 4)):
        source_items = source.get(section) or []
        selected = generated.get(section) or []
        allowed = []
        for item in selected:
            if not isinstance(item, dict):
                continue
            identity = item.get("id") or item.get("name") or item.get("organization")
            original = next((x for x in source_items if isinstance(x, dict) and identity and (x.get("id") == identity or x.get("name") == identity or x.get("organization") == identity)), None)
            if not original:
                continue
            source_text = json.dumps(original)
            score = len(_relevance_tokens(source_text) & jd_tokens)
            if score >= 1:
                # Keep identity and dates authoritative from the master resume,
                # but retain validated AI rewrites for the narrative fields.
                merged = dict(original)
                if section == "projects":
                    if isinstance(item.get("description"), list) and item["description"]:
                        merged["description"] = item["description"]
                elif section == "leadershipVolunteering":
                    if isinstance(item.get("bulletPoints"), list) and item["bulletPoints"]:
                        merged["bulletPoints"] = item["bulletPoints"]
                allowed.append(merged)
        generated[section] = allowed[:limit]
        # Leadership/community evidence is required when the job asks for
        # collaboration, culture, engagement, or stakeholder-facing work. If
        # the model omitted it, deterministically select source-backed records
        # rather than silently producing an incomplete tailored resume.
        if section == "leadershipVolunteering" and not generated[section] and culture_signal:
            ranked = sorted(
                source_items,
                key=lambda item: len(_relevance_tokens(json.dumps(item)) & jd_tokens),
                reverse=True,
            )
            generated[section] = [
                {**item, "bulletPoints": (item.get("bulletPoints") or [])[:2]}
                for item in ranked[:2]
            ]
        if section == "certifications" and not generated[section]:
            relevant = [
                item for item in source_items
                if _relevance_tokens(json.dumps(item)) & jd_tokens
            ]
            # Keep at least one verified credential when the source has
            # certifications; omission must be an explicit, auditable choice.
            generated[section] = (relevant or source_items)[:2]
    return generated


def _sanitize_unsupported_language(source: dict, generated: dict, cover_letter: str | None = None):
    """Remove common JD keyword overclaims while retaining verified equivalents."""
    replacements = {
        r"complex\s+diar(?:y|ies)(?:\s+management)?": "complex travel and logistics coordination",
        r"comprehensive\s+diar(?:y|ies)(?:\s+management)?": "comprehensive travel and logistics coordination",
        r"diar(?:y|ies)\s+(?:optimization|scheduling|management)": "administrative coordination",
        r"expense\s+reconciliations?": "SAP Service Entries and timesheet processing",
        r"invoice\s+(?:processing|preparation)": "administrative record processing",
        r"CRM\s+systems?(?:\s*\([^)]*\))?": "confidential record management",
        r"Microsoft\s+365(?:\s*\([^)]*\))?": "enterprise systems",
        r"briefing\s+(?:pack|packs|material|materials)": "operational documentation",
    }
    def clean(text):
        if not isinstance(text, str):
            return text
        for old, new in replacements.items():
            text = re.sub(old, new, text, flags=re.IGNORECASE)
        return text
    for key in ("professionalSummary",):
        if isinstance(generated.get(key), str):
            generated[key] = clean(generated[key])
    def clean_nested(value):
        if isinstance(value, str):
            return clean(value)
        if isinstance(value, list):
            return [clean_nested(item) for item in value]
        if isinstance(value, dict):
            return {key: clean_nested(item) for key, item in value.items()}
        return value
    for key, value in list(generated.items()):
        if key not in ("skills", "professionalSummary"):
            generated[key] = clean_nested(value)
    skills = generated.get("skills") or {}
    for category, values in list(skills.items()):
        if isinstance(values, list):
            skills[category] = [clean(value) for value in values if value and not re.search(r"CRM|invoice|diar(?:y|ies)|Microsoft\s+365", value, flags=re.IGNORECASE)]
    return generated, clean(cover_letter) if cover_letter else cover_letter

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
        # Repair legacy/imported accounts where Firestore is marked master but
        # the backend snapshot was never synchronized.
        try:
            master_docs = [] if not _firestore_master_lookup_enabled() else list(firestore.client().collection("resumes")
                               .where("uid", "==", user["uid"])
                               .where("isMaster", "==", True)
                               .limit(1).stream())
        except Exception as exc:
            print(f"Firestore master lookup unavailable: {exc}")
            master_docs = []
        if master_docs:
            master_doc = master_docs[0]
            master_data = master_doc.to_dict().get("data") or {}
            resume_snapshot = {
                "uid": user["uid"],
                "firestoreResumeId": master_doc.id,
                "version": 1,
                "structuredData": master_data,
                "active": True,
                "createdAt": datetime.utcnow(),
            }
            await db.db.resume_snapshots.insert_one(resume_snapshot)
        else:
            raise HTTPException(status_code=404, detail="No active resume snapshot found")
    else:
        # Keep an existing snapshot aligned when the user replaces or edits the
        # Firestore-marked master after the first synchronization.
        try:
            master_docs = [] if not _firestore_master_lookup_enabled() else list(firestore.client().collection("resumes")
                               .where("uid", "==", user["uid"])
                               .where("isMaster", "==", True)
                               .limit(1).stream())
        except Exception as exc:
            print(f"Firestore master lookup unavailable: {exc}")
            master_docs = []
        if master_docs:
            current_doc = master_docs[0]
            firestore_id = current_doc.id
            if current_doc.exists:
                current_data = current_doc.to_dict().get("data") or {}
                if (current_data != (resume_snapshot.get("structuredData") or {})
                        or firestore_id != resume_snapshot.get("firestoreResumeId")):
                    await db.db.resume_snapshots.update_one(
                        {"_id": resume_snapshot["_id"]},
                        {"$set": {"structuredData": current_data,
                                   "firestoreResumeId": firestore_id,
                                   "updatedAt": datetime.utcnow()}},
                    )
                    resume_snapshot["structuredData"] = current_data

    # Load system prompt rules dynamically from standalone Markdown files

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
    source_resume = add_source_provenance(resume_snapshot["structuredData"])
    working_resume = source_resume
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
        tailored_resume = _parse_model_json(result.tailoredResume) if result.tailoredResume else None
        tailored_resume = _preserve_source_identity(source_resume, tailored_resume, req.description)
        tailored_resume = _filter_selected_sections(source_resume, tailored_resume, req.description)
        tailored_resume, _ = _sanitize_unsupported_language(source_resume, tailored_resume)
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
    tailored_resume, cover_letter = _sanitize_unsupported_language(
        source_resume, tailored_resume, cover_letter
    )
    # Normalize the model output before validating the public word-count
    # contract. The validator must inspect exactly what will be persisted.
    cover_letter = _enforce_cover_letter_word_limit(cover_letter)
    try:
        if tailored_resume:
            validate_protected_facts(source_resume, tailored_resume)
            validate_source_backed_sections(tailored_resume)
        if type == "coverLetter":
            validate_cover_letter(cover_letter)
    except ArtifactValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Artifact validation failed: {exc}")
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
