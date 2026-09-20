from typing import Any, Literal
from pydantic import BaseModel, Field


class TailoringRunRequest(BaseModel):
    job_id: str
    description: str = Field(min_length=20)
    job_title: str | None = None
    company: str | None = None
    artifact_types: list[Literal["resume", "coverLetter"]] = Field(
        default_factory=lambda: ["resume", "coverLetter"]
    )
    mode: Literal["ai", "hybrid"] = "ai"


class TailoringRunStatus(BaseModel):
    run_id: str
    status: Literal["queued", "running", "passed", "failed"]
    snapshot_id: str
    stages: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
