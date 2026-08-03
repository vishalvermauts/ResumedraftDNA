from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class ConnectorConfig(BaseModel):
    type: str # "greenhouse" | "lever" | "jsonld" | "ai_search" -- primary/legacy connector
    boardToken: Optional[str] = None
    priority: List[str] = [] # ordered fallback chain, e.g. ["greenhouse", "jsonld", "ai_search"]
    configuration: Dict[str, Any] = {}

class WatchlistResolution(BaseModel):
    """Per-(company, provider) discovery state persisted at runtime by
    discover_jobs_task -- lets the polling loop avoid re-walking the full priority chain
    every hour once a company's working provider is known."""
    resolvedConnectorType: Optional[str] = None  # which connector in the chain answered
    resolvedConfig: Dict[str, Any] = {}          # the working {boardToken, companyName, careersUrl}
    connectorStatus: Optional[str] = None        # success_with_jobs | success_empty | not_supported_or_unavailable | error
    lastSuccessAt: Optional[datetime] = None     # last fetch that was a healthy provider response
    consecutiveFailures: int = 0                  # consecutive failed runs of the resolved provider
    etags: Dict[str, str] = {}                    # optional ETags per provider for conditional requests

class CompanyWatchlist(BaseModel):
    companyName: str
    careersUrl: str
    connector: ConnectorConfig
    pollingFrequencyMinutes: int = 720
    enabled: bool = True
    resolved: Optional[WatchlistResolution] = None
