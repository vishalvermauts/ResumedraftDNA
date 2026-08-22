from .base import BaseConnector


class AiSearchConnector(BaseConnector):
    """Last-resort connector: uses Gemini + Google Search grounding to find postings on
    companies with no ATS API and no JSON-LD structured data. Disabled."""

    async def fetch_jobs(self):
        print(f"AI search grounding is permanently disabled. Skipping {self.company_name}")
        return []
