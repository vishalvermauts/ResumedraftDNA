import hashlib
import re
import html as html_lib
from datetime import datetime
from typing import Any, Optional, List

# --- Connector result statuses --------------------------------------------------
# A connector's `fetch_jobs()` always returns a list (empty = "no jobs", whatever
# the reason). To let the polling loop tell *why* it was empty, connectors set a
# coarse status on themselves during fetch that the loop reads afterwards without
# making a second network call.
SUCCESS_WITH_JOBS = "success_with_jobs"
SUCCESS_EMPTY = "success_empty"
NOT_SUPPORTED_OR_UNAVAILABLE = "not_supported_or_unavailable"
ERROR = "error"

ALL_STATUSES = {
    SUCCESS_WITH_JOBS,
    SUCCESS_EMPTY,
    NOT_SUPPORTED_OR_UNAVAILABLE,
    ERROR,
}

# A descriptive, honest User-Agent on every provider HTTP request.
DEFAULT_USER_AGENT = "ResumeDraft-JobBot/1.0 (+https://resumedraft.app; job discovery)"

def default_headers() -> dict:
    return {"User-Agent": DEFAULT_USER_AGENT}


class ConnectorError(Exception):
    """A connector error that is not worth backing the whole provider off."""


class ConnectorBackoffError(ConnectorError):
    """A provider-level failure (429 rate limit / 5xx) that the polling loop should
    back off from for the rest of the run and retry on the next hourly run, rather
    than treating it as a normal 'no jobs' result."""

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
        # Last fetch's coarse status (one of ALL_STATUSES), set as a side effect by
        # connectors whose `fetch_jobs()` makes a single HTTP call. Lets the polling
        # loop read the reason an empty list was returned with no extra request.
        self.status: Optional[str] = None
        # ETag observed on the provider's last response, if the provider supports it.
        self.etag: Optional[str] = None

    async def fetch_jobs(self, etag: Optional[str] = None) -> List[Any]:
        raise NotImplementedError("fetch_jobs must be implemented")

    async def check_availability(self) -> str:
        """Return a coarse provider status for this company/provider. Implementations
        that set `self.status` during fetch_jobs() inherit this cheaply; providers
        observed to have no jobs will return SUCCESS_EMPTY. Before any fetch runs, we
        can't guess, so this defaults to ERROR (treated as 'don't know, try the chain')."""
        if self.status in ALL_STATUSES:
            return self.status
        return ERROR
