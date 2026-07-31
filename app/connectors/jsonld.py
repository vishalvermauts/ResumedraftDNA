import httpx
import json
import re
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location

LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE
)


class JsonLdConnector(BaseConnector):
    """Scrapes schema.org/JobPosting structured data embedded on a company's own careers page.
    No API key required -- most companies embed this for Google Jobs indexing."""

    async def fetch_jobs(self):
        if not self.careers_url:
            return []

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                self.careers_url,
                timeout=15.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ResumeDraftBot/1.0)"}
            )
            response.raise_for_status()
            html = response.text

        jobs = []
        for raw_block in LD_JSON_RE.findall(html):
            try:
                data = json.loads(raw_block.strip())
            except (json.JSONDecodeError, ValueError):
                continue

            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("@type") != "JobPosting":
                    continue

                title = entry.get("title", "")
                apply_url = entry.get("url") or self.careers_url
                description = entry.get("description", "") or ""

                job_location = entry.get("jobLocation", {})
                if isinstance(job_location, list):
                    job_location = job_location[0] if job_location else {}
                address = job_location.get("address", {}) if isinstance(job_location, dict) else {}
                loc_raw = (address.get("addressLocality") if isinstance(address, dict) else None) or "Remote"

                identifier = entry.get("identifier")
                job_id = identifier.get("value") if isinstance(identifier, dict) else (identifier or apply_url)

                h = canonical_hash("jsonld", str(job_id), self.company_name or "", title, loc_raw, apply_url)

                jobs.append(JobPosting(
                    canonicalHash=h,
                    source="jsonld",
                    sourceJobId=str(job_id),
                    companyName=self.company_name or "",
                    title=title,
                    location=[Location(raw=loc_raw)],
                    descriptionText=description,
                    applyUrl=apply_url,
                    canonicalUrl=apply_url
                ))
        return jobs
