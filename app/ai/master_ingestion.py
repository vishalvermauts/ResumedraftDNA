"""Deterministic primitives for bounded master-resume ingestion.

This module deliberately does not call Vertex. It creates stable, bounded
section payloads so a caller can retry one failed section without reparsing or
reprocessing the complete source document.
"""

from __future__ import annotations

from typing import Any


SECTION_ORDER = (
    "personalDetails",
    "professionalSummary",
    "employmentHistory",
    "education",
    "projects",
    "skills",
    "leadershipVolunteering",
    "certifications",
    "customSections",
)


def section_chunks(resume: dict[str, Any], max_items: int = 4) -> list[dict[str, Any]]:
    """Return stable, independently processable extraction chunks."""
    if max_items < 1:
        raise ValueError("max_items must be positive")
    chunks: list[dict[str, Any]] = []
    for section in SECTION_ORDER:
        value = resume.get(section)
        if isinstance(value, list):
            for offset in range(0, len(value), max_items):
                items = value[offset:offset + max_items]
                chunks.append({
                    "chunkId": f"{section}:{offset // max_items + 1:04d}",
                    "section": section,
                    "startIndex": offset,
                    "items": items,
                })
        elif value not in (None, "", {}):
            chunks.append({
                "chunkId": f"{section}:0001",
                "section": section,
                "startIndex": 0,
                "items": value,
            })
    return chunks
