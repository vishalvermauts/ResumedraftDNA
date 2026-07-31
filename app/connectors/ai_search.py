import json
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location
from ..ai.gemini import gemini_client
from ..ai.quota import grounding_quota_available, record_grounding_usage


class AiSearchConnector(BaseConnector):
    """Last-resort connector: uses Gemini + Google Search grounding to find postings on
    companies with no ATS API and no JSON-LD structured data. Quota-guarded to stay free."""

    async def fetch_jobs(self):
        if not await grounding_quota_available():
            print(f"AI search grounding quota exhausted this month, skipping {self.company_name}")
            return []

        target = self.careers_url or self.company_name
        prompt = f"""Search for current open job postings at "{self.company_name}" (careers page: {target}).
Return ONLY a raw JSON array, no markdown fences, no prose. Each item: {{"title": str, "applyUrl": str, "location": str, "description": str}}.
If none found, return []."""

        try:
            text = await gemini_client.generate_grounded(prompt)
            await record_grounding_usage()
        except Exception as e:
            print(f"AI search grounding failed for {self.company_name}: {e}")
            return []

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]

        try:
            listings = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            print(f"AI search returned unparseable output for {self.company_name}")
            return []

        jobs = []
        for item in listings if isinstance(listings, list) else []:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            apply_url = item.get("applyUrl", "")
            if not title or not apply_url:
                continue
            loc_raw = item.get("location") or "Remote"
            h = canonical_hash("ai_search", apply_url, self.company_name or "", title, loc_raw, apply_url)
            jobs.append(JobPosting(
                canonicalHash=h,
                source="ai_search",
                sourceJobId=apply_url,
                companyName=self.company_name or "",
                title=title,
                location=[Location(raw=loc_raw)],
                descriptionText=item.get("description", ""),
                applyUrl=apply_url,
                canonicalUrl=apply_url
            ))
        return jobs
