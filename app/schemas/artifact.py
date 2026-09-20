from pydantic import BaseModel
from typing import Any, Optional

class TailoredArtifact(BaseModel):
    # Keep nested resume data as JSON, not a JSON-encoded string. The old
    # string contract required Vertex to escape every quote in the document and
    # was the source of malformed wrapper responses in live certification.
    tailoredResume: Optional[dict[str, Any]] = None
    coverLetter: Optional[str] = None
