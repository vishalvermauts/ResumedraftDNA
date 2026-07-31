from pydantic import BaseModel
from typing import List, Optional

class AutomationSettings(BaseModel):
    jobTitles: List[str] = []
    locations: List[str] = []
    remoteOnly: bool = False
    salaryMin: Optional[float] = None
    frequencyHours: int = 24
    enabled: bool = False
