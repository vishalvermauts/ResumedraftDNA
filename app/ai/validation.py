"""Deterministic validation for AI-produced ResumeDraft artifacts.

The model may select and rewrite evidence, but it must not change protected
identity facts or produce an undersized cover letter that the UI later treats
as a successful artifact.
"""

from __future__ import annotations

from typing import Any
import json
import re


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


_CLAIM_STOPWORDS = {
    "about", "after", "again", "also", "because", "being", "could", "from",
    "have", "into", "more", "most", "over", "such", "than", "that", "their",
    "there", "these", "they", "this", "through", "using", "were", "which", "with",
}


def _meaningful_tokens(value: Any) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 4 and token not in _CLAIM_STOPWORDS
    }


def _source_evidence_map(source: dict[str, Any] | None) -> dict[str, str]:
    evidence: dict[str, str] = {}
    if not isinstance(source, dict):
        return evidence
    for value in source.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            text = json.dumps(item, ensure_ascii=True)
            for evidence_id in item.get("sourceEvidenceIds") or []:
                if isinstance(evidence_id, str) and evidence_id:
                    evidence[evidence_id] = text
    return evidence


def validate_source_backed_sections(generated: dict[str, Any], source: dict[str, Any] | None = None) -> None:
    """Require selected structured records to retain their master evidence IDs.

    Narrative bullets are allowed to be paraphrased, but they must remain
    inside a record carrying source evidence. This is compatible with the
    existing public payload while preventing untraceable records from being
    persisted.
    """
    evidence_map = _source_evidence_map(source)
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
            for field in ("bulletPoints", "description"):
                claims = item.get(field)
                if not isinstance(claims, list) or not claims:
                    continue
                claim_evidence = item.get("claimEvidenceIds")
                if not isinstance(claim_evidence, list) or len(claim_evidence) != len(claims):
                    raise ArtifactValidationError(
                        f"{section}[{index}].{field} is missing one evidence list per generated claim"
                    )
                for claim_index, claim_ids in enumerate(claim_evidence, 1):
                    if not isinstance(claim_ids, list) or not any(isinstance(x, str) and x for x in claim_ids):
                        raise ArtifactValidationError(
                            f"{section}[{index}].{field}[{claim_index}] is missing claim evidence IDs"
                        )
                    if evidence_map:
                        claim_tokens = _meaningful_tokens(claims[claim_index - 1])
                        cited_text = " ".join(evidence_map.get(evidence_id, "") for evidence_id in claim_ids)
                        if not cited_text or not claim_tokens.intersection(_meaningful_tokens(cited_text)):
                            raise ArtifactValidationError(
                                f"{section}[{index}].{field}[{claim_index}] is not supported by cited source evidence"
                            )


def attach_claim_evidence(generated: dict[str, Any]) -> dict[str, Any]:
    """Attach parent source IDs to each narrative claim without changing text shape."""
    for section in (
        "employmentHistory", "projects", "leadershipVolunteering", "certifications",
    ):
        for item in _items(generated.get(section)):
            source_ids = [x for x in (item.get("sourceEvidenceIds") or []) if isinstance(x, str) and x]
            if not source_ids:
                continue
            for field in ("bulletPoints", "description"):
                claims = item.get(field)
                if isinstance(claims, list) and claims:
                    existing = item.get("claimEvidenceIds")
                    if not isinstance(existing, list) or len(existing) != len(claims):
                        item["claimEvidenceIds"] = [list(source_ids) for _ in claims]
    return generated


def repair_unsupported_claims(generated: dict[str, Any], source: dict[str, Any] | None) -> dict[str, Any]:
    """Replace unsupported model paraphrases with source-backed wording.

    The release gate remains fail-closed: this is a deterministic repair before
    validation, not an exemption. Identity fields and selected records remain
    unchanged; only a narrative claim that cannot be supported by its cited
    source is reverted to the matching master claim.
    """
    if not isinstance(generated, dict) or not isinstance(source, dict):
        return generated
    evidence_map = _source_evidence_map(source)
    for section in ("employmentHistory", "projects", "leadershipVolunteering", "certifications"):
        source_items = _items(source.get(section))
        for item in _items(generated.get(section)):
            if not isinstance(item, dict):
                continue
            identity = item.get("id") or item.get("name") or item.get("organization")
            original = next((candidate for candidate in source_items
                             if isinstance(candidate, dict) and identity and
                             (candidate.get("id") == identity or candidate.get("name") == identity or candidate.get("organization") == identity)), None)
            if not original:
                continue
            for field in ("bulletPoints", "description"):
                claims = item.get(field)
                source_claims = original.get(field)
                if not isinstance(claims, list) or not claims or not isinstance(source_claims, list) or not source_claims:
                    continue
                cited_ids = item.get("claimEvidenceIds") if isinstance(item.get("claimEvidenceIds"), list) else []
                repaired = []
                for index, claim in enumerate(claims):
                    claim_ids = cited_ids[index] if index < len(cited_ids) and isinstance(cited_ids[index], list) else item.get("sourceEvidenceIds") or []
                    cited_text = " ".join(evidence_map.get(evidence_id, "") for evidence_id in claim_ids)
                    if not cited_text or not _meaningful_tokens(claim).intersection(_meaningful_tokens(cited_text)):
                        repaired.append(source_claims[index] if index < len(source_claims) else source_claims[0])
                    else:
                        repaired.append(claim)
                item[field] = repaired
                item.pop("claimEvidenceIds", None)
    return generated
