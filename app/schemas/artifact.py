from pydantic import BaseModel
from typing import Dict, Any, Optional

class TailoredArtifact(BaseModel):
    tailoredResume: Dict[str, Any]
    coverLetter: Optional[str] = None
