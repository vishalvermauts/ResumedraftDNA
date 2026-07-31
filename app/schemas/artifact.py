from pydantic import BaseModel
from typing import Optional

class TailoredArtifact(BaseModel):
    tailoredResume: str  # JSON-encoded string mirroring the master resume's structuredData shape
    coverLetter: Optional[str] = None
