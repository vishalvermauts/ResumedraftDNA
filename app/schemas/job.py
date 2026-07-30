from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Salary(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    currency: str = "USD"
    period: str = "year" # "hour", "day", "month", "year"
    isEstimate: bool = False

class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: str = "US"
    raw: str

class JobPosting(BaseModel):
    canonicalHash: str
    source: str # "greenhouse", "lever", "manual"
    sourceJobId: str
    companyName: str
    title: str
    location: List[Location] = []
    type: Optional[str] = None # "full_time", etc.
    workplaceType: Optional[str] = None # "remote", "hybrid", "onsite"
    salary: Optional[Salary] = None
    descriptionText: str
    applyUrl: str
    canonicalUrl: str
    postedAt: Optional[datetime] = None
    discoveredAt: datetime = Field(default_factory=datetime.utcnow)
