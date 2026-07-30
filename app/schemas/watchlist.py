from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class ConnectorConfig(BaseModel):
    type: str # "greenhouse" | "lever" | "ashby" | "jsonld"
    boardToken: Optional[str] = None
    configuration: Dict[str, Any] = {}

class CompanyWatchlist(BaseModel):
    companyName: str
    careersUrl: str
    connector: ConnectorConfig
    pollingFrequencyMinutes: int = 720
    enabled: bool = True
