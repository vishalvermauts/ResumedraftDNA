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

SOURCE_SECTION_ALIASES = {
    "experience": "employmentHistory",
    "work experience": "employmentHistory",
    "employment": "employmentHistory",
    "education": "education",
    "projects": "projects",
    "skills": "skills",
    "technical skills": "skills",
    "technical skills overview": "skills",
    "leadership volunteering": "leadershipVolunteering",
    "leadership and volunteering": "leadershipVolunteering",
    "certifications": "certifications",
}


def source_section_chunks(raw_text: str, max_lines: int = 120) -> list[dict[str, Any]]:
    """Split raw resume text into bounded, provenance-bearing sections."""
    if max_lines < 1:
        raise ValueError("max_lines must be positive")
    lines = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return []
    sections: list[dict[str, Any]] = []
    active = "header"
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        for offset in range(0, len(current), max_lines):
            part = current[offset:offset + max_lines]
            sections.append({
                "chunkId": f"source:{active}:{offset // max_lines + 1:04d}",
                "section": active,
                "startLine": part[0]["line"],
                "endLine": part[-1]["line"],
                "lines": part,
                "text": "\n".join(item["text"] for item in part),
            })
        current = []

    for line_number, text in enumerate(lines, 1):
        key = " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())
        next_section = SOURCE_SECTION_ALIASES.get(key)
        if next_section:
            flush()
            active = next_section
        current.append({"sourceId": f"p{line_number:04d}", "line": line_number, "text": text})
    flush()
    return sections


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
