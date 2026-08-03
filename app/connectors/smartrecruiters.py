import httpx
from .base import (
    BaseConnector,
    canonical_hash,
    html_to_text,
    default_headers,
    SUCCESS_WITH_JOBS,
    SUCCESS_EMPTY,
    NOT_SUPPORTED_OR_UNAVAILABLE,
    ERROR,
    ConnectorError,
    ConnectorBackoffError,
)
from ..schemas.job import JobPosting, Location


# A 200 with this shape means the company's public posting feed is empty, which is
# plan-dependent (many companies on SmartRecruiters don't expose a public feed).
_NOT_AVAILABLE_BODIES = None


def _description_to_text(desc) -> str:
    """SmartRecruiters returns the posting description as either plain text or a
    nested structure (sections). Flatten the ones we can read into plain text."""
    if not desc:
        return ""
    if isinstance(desc, str):
        return html_to_text(desc)
    if isinstance(desc, dict):
        text = desc.get("text") or desc.get("description")
        if text:
            return html_to_text(str(text))
        parts = []
        for section in desc.get("jobAdSectionList") or []:
            body = section.get("text") or section.get("body")
            if body:
                parts.append(html_to_text(str(body)))
        return "\n\n".join(p for p in parts if p)
    return ""


class SmartRecruitersConnector(BaseConnector):
    """Fetches postings from SmartRecruiters' public Postings API for a company
    (`config["boardToken"]` = the `companyId`). No auth. Plan-dependent: a 404/403/
    400 or a 200 with totalFound == 0 means this company simply doesn't expose a
    public feed, so `fetch_jobs()` returns [] without raising so the polling loop can
    fall through to the next connector type. A 429 / 5xx backs the provider off for
    the run. Response shape verified live (2026): top-level `{"totalFound", ...,
    "content": [...]}` where each item has `id`, `name`, `location{city,country}`,
    `applyUrl`, `url`, `description`."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = (
            f"https://api.smartrecruiters.com/v1/companies/{self.board_token}/postings"
        )

    async def fetch_jobs(self, etag=None):
        headers = default_headers()
        if etag:
            headers["If-None-Match"] = etag

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(self.base_url, headers=headers)

        # Plan-dependent / not-available: not an error, return [] so the priority chain
        # can fall through to the next connector type.
        if response.status_code in (404, 403, 400):
            self.status = NOT_SUPPORTED_OR_UNAVAILABLE
            return []
        if response.status_code == 304:
            self.status = SUCCESS_EMPTY
            return []
        if response.status_code == 429 or response.status_code >= 500:
            self.status = ERROR
            raise ConnectorBackoffError(
                f"SmartRecruiters company {self.board_token!r} returned HTTP {response.status_code}"
            )
        if response.status_code != 200:
            self.status = ERROR
            raise ConnectorError(
                f"SmartRecruiters company {self.board_token!r} returned HTTP {response.status_code}"
            )

        self.etag = response.headers.get("etag")

        try:
            data = response.json()
        except ValueError:
            self.status = ERROR
            raise ConnectorError(
                f"SmartRecruiters company {self.board_token!r} returned non-JSON body"
            )

        # SmartRecruiters frequently 200s with an empty feed when a company has no
        # public postings configured. No docs to ingest and not an error.
        content = data.get("content") or []
        if not content:
            self.status = NOT_SUPPORTED_OR_UNAVAILABLE
            return []

        jobs = []
        for item in content:
            job_id = str(item.get("id") or item.get("refNumber") or item.get("ref") or "")
            title = item.get("name") or item.get("jobTitle")
            if not job_id or not title:
                continue
            loc = item.get("location") or {}
            city = (loc.get("city") or "") if isinstance(loc, dict) else ""
            country = (loc.get("country") or "") if isinstance(loc, dict) else ""
            loc_raw = ", ".join(p for p in (city, country) if p) or "Remote"
            canonical_url = item.get("url") or item.get("applyUrl") or ""
            apply_url = item.get("applyUrl") or canonical_url
            h = canonical_hash(
                "smartrecruiters", job_id, self.board_token or "", title, loc_raw, canonical_url
            )
            jobs.append(JobPosting(
                canonicalHash=h,
                source="smartrecruiters",
                sourceJobId=job_id,
                companyName=self.board_token or self.company_name or "",
                title=title,
                location=[Location(raw=loc_raw)],
                descriptionText=_description_to_text(item.get("description")),
                applyUrl=apply_url,
                canonicalUrl=canonical_url,
            ))

        self.status = SUCCESS_WITH_JOBS if jobs else SUCCESS_EMPTY
        return jobs