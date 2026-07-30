from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class ResumeSnapshot(BaseModel):
    firestoreResumeId: str
    version: int
    contentHash: str
    structuredData: Dict[str, Any]
    active: bool = True
