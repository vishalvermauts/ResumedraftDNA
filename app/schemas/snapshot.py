from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class ResumeSnapshot(BaseModel):
    firestoreResumeId: Optional[str] = None
    version: int = 1
    contentHash: Optional[str] = None
    sourceFileHash: Optional[str] = None
    sourceTextHash: Optional[str] = None
    schemaVersion: str = "resume-v1"
    structuredData: Dict[str, Any]
    active: bool = True
