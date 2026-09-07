from pydantic import BaseModel
from typing import List, Optional

class AutomationSettings(BaseModel):
    jobTitles: List[str] = []
    locations: List[str] = []
    remoteOnly: bool = False
    salaryMin: Optional[float] = None
    frequencyHours: int = 24
    enabled: bool = False
    # Optional: only keep matches whose description mentions visa sponsorship (see
    # worker.py's _mentions_sponsorship -- a description-text filter applied uniformly across
    # every source, not a native query param on any connector).
    visaSponsorshipOnly: bool = False
    # Which supported structured connectors may contribute matches. Empty means no restriction
    # across supported connectors; the disabled ai_search compatibility path is never accepted.
    sources: List[str] = []
