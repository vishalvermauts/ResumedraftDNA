"""Deterministic validation for AI-produced ResumeDraft artifacts.

The model may select and rewrite evidence, but it must not change protected
identity facts or produce an undersized cover letter that the UI later treats
as a successful artifact.
"""

from __future__ import annotations

from typing import Any


class ArtifactValidationError(ValueError):
    """Raised when an artifact violates a release-critical invariant."""


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def validate_protected_facts(source: dict[str, Any], generated: dict[str, Any]) -> None:
    """Reject renamed or invented employment records before persistence."""
    source_jobs = _items(source.get("employmentHistory"))
    generated_jobs = _items(generated.get("employmentHistory"))
    generated_pairs = {
        (item.get("company"), item.get("jobTitle")) for item in generated_jobs
    }
    missing = [
        (item.get("company"), item.get("jobTitle"))
        for item in source_jobs
        if item.get("company") and item.get("jobTitle")
        and (item.get("company"), item.get("jobTitle")) not in generated_pairs
    ]
    invented = [
        pair for pair in generated_pairs
        if pair[0] and pair[1]
        and pair not in {
            (item.get("company"), item.get("jobTitle")) for item in source_jobs
        }
    ]
    if invented:
        raise ArtifactValidationError(
            f"Generated employment records are not source-backed: {invented}"
        )
    # Tailoring may select fewer roles, but any retained role must be exact.
    # Dates are protected whenever the model returns them.
    source_by_pair = {
        (item.get("company"), item.get("jobTitle")): item for item in source_jobs
    }
    for item in generated_jobs:
        source_item = source_by_pair.get((item.get("company"), item.get("jobTitle")))
        if not source_item:
            continue
        for field in ("startDate", "endDate"):
            if item.get(field) and item.get(field) != source_item.get(field):
                raise ArtifactValidationError(
                    f"Protected employment fact changed: {field} for {item.get('jobTitle')}"
                )


def validate_cover_letter(text: str | None, minimum: int = 250, maximum: int = 350) -> None:
    """Require a usable cover letter, rather than silently truncating it."""
    words = len((text or "").split())
    if words < minimum or words > maximum:
        raise ArtifactValidationError(
            f"Cover letter must contain {minimum}-{maximum} words; received {words}"
        )


def validate_source_backed_sections(generated: dict[str, Any]) -> None:
    """Require selected structured records to retain their master evidence IDs.

    Narrative bullets are allowed to be paraphrased, but they must remain
    inside a record carrying source evidence. This is compatible with the
    existing public payload while preventing untraceable records from being
    persisted.
    """
    for section in (
        "employmentHistory", "education", "projects", "certifications",
        "leadershipVolunteering", "technicalSkills", "skills",
    ):
        for index, item in enumerate(_items(generated.get(section)), 1):
            evidence = item.get("sourceEvidenceIds")
            if not isinstance(evidence, list) or not any(isinstance(x, str) and x for x in evidence):
                raise ArtifactValidationError(
                    f"{section}[{index}] is missing source evidence IDs"
                )
