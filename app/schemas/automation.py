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
    # Which connector(s) may contribute matches: "greenhouse" | "lever" | "jsonld" | "ashby" |
    # "recruitee" | "smartrecruiters" | "adzuna" | "ai_search". Empty = no restriction (every
    # source), which is also what a pre-existing doc without this field gets -- backward
    # compatible with the original always-on behavior. See worker.py's _run_discovery_for_one.
    sources: List[str] = []
