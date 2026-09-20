from pydantic import BaseModel, field_validator
from typing import Any, Optional

class TailoredArtifact(BaseModel):
    # Keep nested resume data as JSON, not a JSON-encoded string. The old
    # string contract required Vertex to escape every quote in the document and
    # was the source of malformed wrapper responses in live certification.
    tailoredResume: Optional[dict[str, Any]] = None
    coverLetter: Optional[str] = None


class CoverLetterArtifact(TailoredArtifact):
    """A cover-letter response that is safe to accept from the retry loop."""

    coverLetter: str

    @field_validator("coverLetter")
    @classmethod
    def enforce_word_contract(cls, value: str) -> str:
        words = len(value.split())
        if not 250 <= words <= 350:
            raise ValueError(f"coverLetter must contain 250-350 words; received {words}")
        return value
