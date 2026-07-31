import json
from datetime import datetime, timezone
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location
from ..ai.gemini import gemini_client
from ..db.mongo import db

# Google's free grounded-prompt quota is ~5,000/month for the Gemini 3 family (shared across
# all callers on the project). Keep a buffer so we never actually cross into billed usage.
FREE_TIER_MONTHLY_LIMIT = 4500


class AiSearchConnector(BaseConnector):
    """Last-resort connector: uses Gemini + Google Search grounding to find postings on
    companies with no ATS API and no JSON-LD structured data. Quota-guarded to stay free."""

    async def fetch_jobs(self):
        if not await self._quota_available():
            print(f"AI search grounding quota exhausted this month, skipping {self.company_name}")
            return []

        target = self.careers_url or self.company_name
        prompt = f"""Search for current open job postings at "{self.company_name}" (careers page: {target}).
Return ONLY a raw JSON array, no markdown fences, no prose. Each item: {{"title": str, "applyUrl": str, "location": str, "description": str}}.
If none found, return []."""

        try:
            text = await gemini_client.generate_grounded(prompt)
            await self._record_usage()
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

    async def _quota_available(self) -> bool:
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        doc = await db.db.api_usage_counters.find_one({"_id": f"gemini_grounding_{month_key}"})
        count = doc["count"] if doc else 0
        return count < FREE_TIER_MONTHLY_LIMIT

    async def _record_usage(self):
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        await db.db.api_usage_counters.update_one(
            {"_id": f"gemini_grounding_{month_key}"},
            {"$inc": {"count": 1}},
            upsert=True
        )
