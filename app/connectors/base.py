import hashlib
import re
import html as html_lib
from typing import Optional

_BLOCK_TAG_RE = re.compile(r'</(p|div|li|h[1-6])\s*>|<br\s*/?>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\n{3,}')


def html_to_text(raw_html: str) -> str:
    """Converts a raw HTML job description (e.g. Greenhouse's `content` field) into readable
    plain text -- block-level tags become line breaks, everything else is stripped, entities
    are decoded. Good enough for display; not a full HTML renderer."""
    if not raw_html:
        return ""
    text = _BLOCK_TAG_RE.sub('\n', raw_html)
    text = _TAG_RE.sub('', text)
    text = html_lib.unescape(text)
    text = _WHITESPACE_RE.sub('\n\n', text)
    return text.strip()

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
    """config: {"boardToken": str|None, "companyName": str|None, "careersUrl": str|None}"""
    def __init__(self, config: dict):
        self.config = config or {}
        self.board_token = self.config.get("boardToken")
        self.company_name = self.config.get("companyName")
        self.careers_url = self.config.get("careersUrl")

    async def fetch_jobs(self):
        raise NotImplementedError("fetch_jobs must be implemented")
