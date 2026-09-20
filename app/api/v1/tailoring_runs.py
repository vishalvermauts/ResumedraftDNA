"""Durable orchestration for resume and cover-letter generation.

The user-facing builder and certification runner both use this route so a
successful certification exercises the same snapshot and tailoring code as the
application.
"""
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from ...auth import get_current_user
from ...db.mongo import db
from ...schemas.tailoring_run import TailoringRunRequest, TailoringRunStatus
from .tailor import TailorRequest, tailor_resume

router = APIRouter()


def _now():
    return datetime.now(timezone.utc)


async def _set_stage(run_id: ObjectId, name: str, status: str, **extra):
    stage = {"name": name, "status": status, "updatedAt": _now(), **extra}
    await db.db.tailoring_runs.update_one(
        {"_id": run_id},
        {"$push": {"stages": stage}, "$set": {"updatedAt": _now()}},
    )
    return stage


@router.post("/tailoring-runs", response_model=TailoringRunStatus, status_code=202)
async def create_tailoring_run(
    req: TailoringRunRequest,
    user: dict = Depends(get_current_user),
):
    snapshot = await db.db.resume_snapshots.find_one({"uid": user["uid"], "active": True})
    if not snapshot:
        raise HTTPException(status_code=404, detail="No active master resume snapshot found")

    run = {
        "uid": user["uid"],
        "status": "queued",
        "snapshotId": str(snapshot["_id"]),
        "snapshotContentHash": snapshot.get("contentHash"),
        "job": {
            "id": req.job_id,
            "title": req.job_title,
            "company": req.company,
            "description": req.description,
        },
        "mode": req.mode,
        "artifactTypes": req.artifact_types,
        "stages": [{"name": "PREFLIGHT", "status": "passed", "updatedAt": _now()}],
        "artifacts": [],
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    inserted = await db.db.tailoring_runs.insert_one(run)
    run_id = inserted.inserted_id
    await db.db.tailoring_runs.update_one({"_id": run_id}, {"$set": {"status": "running"}})

    try:
        for artifact_type in req.artifact_types:
            stage_name = "RESUME_GENERATION" if artifact_type == "resume" else "COVER_LETTER_GENERATION"
            await _set_stage(run_id, stage_name, "running")
            result = await tailor_resume(
                job_id=req.job_id,
                req=TailorRequest(description=req.description),
                type=artifact_type,
                mode=req.mode,
                snapshot_id=str(snapshot["_id"]),
                user=user,
            )
            await db.db.tailoring_runs.update_one(
                {"_id": run_id},
                {"$push": {"artifacts": {"type": artifact_type, "data": result["data"], "createdAt": _now()}}},
            )
            await _set_stage(run_id, stage_name, "passed")

        await db.db.tailoring_runs.update_one(
            {"_id": run_id}, {"$set": {"status": "passed", "updatedAt": _now()}},
        )
    except Exception as exc:
        await _set_stage(run_id, "FAILED", "failed", error=str(exc))
        await db.db.tailoring_runs.update_one(
            {"_id": run_id}, {"$set": {"status": "failed", "error": str(exc), "updatedAt": _now()}},
        )

    stored = await db.db.tailoring_runs.find_one({"_id": run_id})
    return TailoringRunStatus(
        run_id=str(run_id), status=stored["status"], snapshot_id=stored["snapshotId"],
        stages=stored.get("stages", []), artifacts=stored.get("artifacts", []), error=stored.get("error"),
    )


@router.get("/tailoring-runs/{run_id}", response_model=TailoringRunStatus)
async def get_tailoring_run(run_id: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(status_code=404, detail="Tailoring run not found")
    stored = await db.db.tailoring_runs.find_one({"_id": ObjectId(run_id), "uid": user["uid"]})
    if not stored:
        raise HTTPException(status_code=404, detail="Tailoring run not found")
    return TailoringRunStatus(
        run_id=str(stored["_id"]), status=stored["status"], snapshot_id=stored["snapshotId"],
        stages=stored.get("stages", []), artifacts=stored.get("artifacts", []), error=stored.get("error"),
    )
