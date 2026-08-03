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


class RecruiteeConnector(BaseConnector):
    """Fetches open offers from Recruitee's public offers API for a company subdomain
    (`config["boardToken"]` = the `{company}` in `{company}.recruitee.com`). No auth.
    Response shape verified live (2026): top-level `{"offers": [...]}` where each offer
    has `id`, `title`, `location`, `careers_url`, `careers_apply_url`, `description` and
    `requirements` (HTML), `status`, `remote`/`hybrid`, `employment_type_code`."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = f"https://{self.board_token}.recruitee.com/api/offers/"

    async def fetch_jobs(self, etag=None):
        headers = default_headers()
        if etag:
            headers["If-None-Match"] = etag

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(self.base_url, headers=headers)

        if response.status_code == 404:
            # No such company subdomain; "not available for this company."
            self.status = NOT_SUPPORTED_OR_UNAVAILABLE
            return []
        if response.status_code == 304:
            self.status = SUCCESS_EMPTY
            return []
        if response.status_code == 429 or response.status_code >= 500:
            self.status = ERROR
            raise ConnectorBackoffError(
                f"Recruitee company {self.board_token!r} returned HTTP {response.status_code}"
            )
        if response.status_code != 200:
            self.status = ERROR
            raise ConnectorError(
                f"Recruitee company {self.board_token!r} returned HTTP {response.status_code}"
            )

        self.etag = response.headers.get("etag")

        try:
            data = response.json()
        except ValueError:
            self.status = ERROR
            raise ConnectorError(f"Recruitee company {self.board_token!r} returned non-JSON body")

        jobs = []
        for offer in data.get("offers", []):
            if offer.get("status") in ("closed", "draft"):
                continue
            job_id = str(offer.get("id"))
            title = offer.get("title")
            if not job_id or not title:
                continue
            loc_raw = offer.get("location") or "Remote"
            canonical_url = offer.get("careers_url") or offer.get("careers_apply_url") or ""
            apply_url = offer.get("careers_apply_url") or canonical_url
            description = html_to_text(
                "\n\n".join(
                    p for p in (offer.get("description"), offer.get("requirements"))
                    if p
                )
            )
            h = canonical_hash(
                "recruitee", job_id, self.board_token or "", title, loc_raw, canonical_url
            )
            jobs.append(JobPosting(
                canonicalHash=h,
                source="recruitee",
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