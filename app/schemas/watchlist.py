from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class ConnectorConfig(BaseModel):
    type: str # "greenhouse" | "lever" | "jsonld" | "ai_search" -- primary/legacy connector
    boardToken: Optional[str] = None
    priority: List[str] = [] # ordered fallback chain, e.g. ["greenhouse", "jsonld", "ai_search"]
    configuration: Dict[str, Any] = {}

class CompanyWatchlist(BaseModel):
    companyName: str
    careersUrl: str
    connector: ConnectorConfig
    pollingFrequencyMinutes: int = 720
    enabled: bool = True
