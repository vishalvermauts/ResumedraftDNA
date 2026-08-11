import json
import os
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location
from ..ai.gemini import gemini_client
from ..ai.quota import grounding_quota_available, record_grounding_usage


class AiSearchConnector(BaseConnector):
    """Last-resort connector: uses Gemini + Google Search grounding to find postings on
    companies with no ATS API and no JSON-LD structured data. Disabled."""

    async def fetch_jobs(self):
        if os.getenv("ENABLE_GEMINI_GROUNDING", "false").lower() != "true":
            print(f"AI search grounding is disabled by ENABLE_GEMINI_GROUNDING. Skipping {self.company_name}")
            return []
        print(f"AI search grounding is disabled. Skipping {self.company_name}")
        return []
