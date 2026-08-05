import asyncio
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

# Cap concurrent per-job detail requests so a company with a large board (seen: 100+ postings)
# doesn't fire that many simultaneous connections at once.
_DETAIL_FETCH_CONCURRENCY = 10


# A 200 with this shape means the company's public posting feed is empty, which is
# plan-dependent (many companies on SmartRecruiters don't expose a public feed).
_NOT_AVAILABLE_BODIES = None


class SmartRecruitersConnector(BaseConnector):
    """Fetches postings from SmartRecruiters' public Postings API for a company
    (`config["boardToken"]` = the `companyId`). No auth. Plan-dependent: a 404/403/
    400 or a 200 with totalFound == 0 means this company simply doesn't expose a
    public feed, so `fetch_jobs()` returns [] without raising so the polling loop can
    fall through to the next connector type. A 429 / 5xx backs the provider off for
    the run. Response shape verified live (2026): top-level `{"totalFound", ...,
    "content": [...]}` where each item has `id`, `name`, `location{city,country}`,
    `applyUrl`, `url` -- NOT a usable `description`: the list endpoint's `description`
    key is always absent/None (only a `defaultJobAd: true` boolean flag), the real text
    only exists behind a per-posting detail call (`GET .../postings/{id}`, response
    `jobAd.sections.{companyDescription,jobDescription,qualifications,
    additionalInformation}.text`, each an HTML string, some empty). Confirmed live: a
    naive read of the list item's `description` silently produced an empty string for
    every SmartRecruiters job ever ingested, which meant description-text search/
    filtering (e.g. automation's visaSponsorshipOnly) could never match a SmartRecruiters
    posting even when the real text plainly said "eligible for visa sponsorship"."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = (
            f"https://api.smartrecruiters.com/v1/companies/{self.board_token}/postings"
        )

    async def _fetch_description(self, client: httpx.AsyncClient, posting_id: str, sem: asyncio.Semaphore) -> str:
        async with sem:
            try:
                resp = await client.get(f"{self.base_url}/{posting_id}", headers=default_headers())
                if resp.status_code != 200:
                    return ""
                sections = (resp.json().get("jobAd") or {}).get("sections") or {}
                parts = [html_to_text(sec.get("text", "")) for sec in sections.values() if sec.get("text")]
                return "\n\n".join(parts)
            except (httpx.HTTPError, ValueError):
                # A single posting's detail call failing (timeout, bad JSON, etc.) shouldn't
                # drop the posting entirely -- it still has a real title/url/location, just
                # without description text this one time.
                return ""

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

        valid_items = []
        for item in content:
            job_id = str(item.get("id") or item.get("refNumber") or item.get("ref") or "")
            title = item.get("name") or item.get("jobTitle")
            if job_id and title:
                valid_items.append((job_id, title, item))

        # The list endpoint never has real description text (see class docstring) -- fetch it
        # per-posting, concurrently (capped), so descriptionText is actually searchable/
        # filterable instead of silently always empty.
        sem = asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY)
        async with httpx.AsyncClient(timeout=15.0) as detail_client:
            descriptions = await asyncio.gather(*[
                self._fetch_description(detail_client, job_id, sem) for job_id, _, _ in valid_items
            ])

        jobs = []
        for (job_id, title, item), description in zip(valid_items, descriptions):
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
                descriptionText=description,
                applyUrl=apply_url,
                canonicalUrl=canonical_url,
            ))

        self.status = SUCCESS_WITH_JOBS if jobs else SUCCESS_EMPTY
        return jobs