import hashlib
from typing import Optional

def canonical_hash(
    source: str, 
    source_job_id: str, 
    company_domain: str, 
    title: str, 
    location: str, 
    url: str
) -> str:
    # Normalize inputs
    c = (company_domain or "").lower().strip()
    t = (title or "").lower().strip()
    l = (location or "").lower().strip()
    u = (url or "").lower().strip()
    
    # If source ID exists, it's the strongest identifier
    if source and source_job_id:
        raw = f"{source}:{source_job_id}"
    else:
        # Fallback: Hash of normalized content
        raw = f"{c}|{t}|{l}|{u}"
    
    return hashlib.sha256(raw.encode()).hexdigest()

class BaseConnector:
    def __init__(self, board_token: str):
        self.board_token = board_token
    
    async def fetch_jobs(self):
        raise NotImplementedError("fetch_jobs must be implemented")
