import httpx
from .base import (
    BaseConnector,
    canonical_hash,
    default_headers,
    SUCCESS_WITH_JOBS,
    SUCCESS_EMPTY,
    NOT_SUPPORTED_OR_UNAVAILABLE,
    ERROR,
    ConnectorError,
    ConnectorBackoffError,
)
from ..schemas.job import JobPosting, Location


class AshbyConnector(BaseConnector):
    """Fetches open jobs from Ashby's public Posting API for a single job board.
    `config["boardToken"]` is the board's `jobBoardName` (e.g. the company slug).
    No authentication required. Response shape verified live (2026): top-level
    `{"jobs": [...]}` where each job has `id`, `title`, `location`, `jobUrl`,
    `applyUrl`, `descriptionPlain`, `publishedAt`, `isRemote`, `employmentType`."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = (
            f"https://api.ashbyhq.com/posting-api/job-board/{self.board_token}"
        )

    async def fetch_jobs(self, etag=None):
        headers = default_headers()
        if etag:
            headers["If-None-Match"] = etag

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(self.base_url, headers=headers)

        if response.status_code == 404:
            # No board with this name; treat as "not available for this company."
            self.status = NOT_SUPPORTED_OR_UNAVAILABLE
            return []
        if response.status_code == 304:
            # Not modified since our stored ETag -- no new jobs.
            self.status = SUCCESS_EMPTY
            return []
        if response.status_code == 429 or response.status_code >= 500:
            self.status = ERROR
            raise ConnectorBackoffError(
                f"Ashby board {self.board_token!r} returned HTTP {response.status_code}"
            )
        if response.status_code != 200:
            self.status = ERROR
            raise ConnectorError(
                f"Ashby board {self.board_token!r} returned HTTP {response.status_code}"
            )

        self.etag = response.headers.get("etag")

        try:
            data = response.json()
        except ValueError:
            self.status = ERROR
            raise ConnectorError(f"Ashby board {self.board_token!r} returned non-JSON body")

        jobs = []
        for job in data.get("jobs", []):
            job_id = str(job.get("id"))
            title = job.get("title")
            if not job_id or not title:
                continue
            loc_raw = job.get("location") or "Remote"
            canonical_url = job.get("jobUrl") or job.get("applyUrl") or ""
            apply_url = job.get("applyUrl") or canonical_url
            h = canonical_hash(
                "ashby", job_id, self.board_token or "", title, loc_raw, canonical_url
            )
            jobs.append(JobPosting(
                canonicalHash=h,
                source="ashby",
                sourceJobId=job_id,
                companyName=self.board_token or self.company_name or "",
                title=title,
                location=[Location(raw=loc_raw)],
                descriptionText=job.get("descriptionPlain") or job.get("descriptionText") or "",
                applyUrl=apply_url,
                canonicalUrl=canonical_url,
            ))

        self.status = SUCCESS_WITH_JOBS if jobs else SUCCESS_EMPTY
        return jobs