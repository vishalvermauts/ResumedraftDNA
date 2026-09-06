"""Deterministic master-resume snapshot primitives.

These helpers are deliberately independent of Vertex, Firestore, and Mongo so
the same snapshot identity can be used in local, Docker, CI, and production.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


SNAPSHOT_SCHEMA_VERSION = "resume-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def add_source_provenance(resume: dict[str, Any], source_prefix: str = "master") -> dict[str, Any]:
    """Attach stable evidence IDs without changing user-visible resume values."""
    snapshot = deepcopy(resume)
    counters: dict[str, int] = {}

    def evidence(section: str, item: Any, index: int) -> Any:
        if not isinstance(item, dict):
            return item
        result = dict(item)
        result.setdefault("sourceEvidenceIds", [f"{source_prefix}:{section}:{index:04d}"])
        return result

    for section in (
        "employmentHistory", "education", "projects", "certifications",
        "leadershipVolunteering", "technicalSkills", "skills",
    ):
        value = snapshot.get(section)
        if isinstance(value, list):
            snapshot[section] = [evidence(section, item, index) for index, item in enumerate(value, 1)]
            counters[section] = len(snapshot[section])

    metadata = dict(snapshot.get("metadata") or {})
    metadata["schemaVersion"] = SNAPSHOT_SCHEMA_VERSION
    metadata["contentHash"] = content_hash({key: value for key, value in snapshot.items() if key != "metadata"})
    metadata["parseStatus"] = "validated"
    metadata["sectionCounts"] = counters
    snapshot["metadata"] = metadata
    return snapshot

