import os
from datetime import datetime
import httpx
from .base import (
    BaseConnector,
    canonical_hash,
    html_to_text,
    default_headers,
    SUCCESS_WITH_JOBS,
    SUCCESS_EMPTY,
    ERROR,
    ConnectorError,
    ConnectorBackoffError,
)
from ..schemas.job import JobPosting, Location, Salary

# Adzuna's search endpoint is per-country, not per-company-board like the ATS connectors --
# `config["boardToken"]`/`companyName` is used as the `company` query filter against Adzuna's
# aggregate index rather than a company-owned board slug. Country defaults to "us"; override
# per watchlist entry via `connector.configuration.country` (a 2-letter Adzuna country code --
# gb, us, in, au, etc. -- see https://developer.adzuna.com/docs/search).
_CURRENCY_BY_COUNTRY = {
    "gb": "GBP", "us": "USD", "au": "AUD", "at": "EUR", "br": "BRL", "ca": "CAD",
    "de": "EUR", "fr": "EUR", "in": "INR", "it": "EUR", "nl": "EUR", "nz": "NZD",
    "pl": "PLN", "sg": "SGD", "za": "ZAR", "es": "EUR", "mx": "MXN",
}


def _parse_results(data: dict, country: str, fallback_company: str = "") -> list[JobPosting]:
    """Shared response mapping for both the per-company connector below and the free-text
    keyword search used by personalized automation (app/worker.py) -- same response shape
    either way, only the query params that produced `data` differ."""
    currency = _CURRENCY_BY_COUNTRY.get(country, "USD")
    jobs = []
    for item in data.get("results", []):
        job_id = str(item.get("id") or "")
        title = item.get("title")
        if not job_id or not title:
            continue

        loc = item.get("location") or {}
        loc_raw = loc.get("display_name") or "Remote"
        url = item.get("redirect_url") or ""
        company_display = (item.get("company") or {}).get("display_name") or fallback_company

        salary = None
        if item.get("salary_min") or item.get("salary_max"):
            salary = Salary(
                min=item.get("salary_min"),
                max=item.get("salary_max"),
                currency=currency,
                period="year",
                isEstimate=str(item.get("salary_is_predicted")) == "1",
            )

        posted_at = None
        created = item.get("created")
        if created:
            try:
                posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        h = canonical_hash("adzuna", job_id, company_display, title, loc_raw, url)
        jobs.append(JobPosting(
            canonicalHash=h,
            source="adzuna",
            sourceJobId=job_id,
            companyName=company_display,
            title=title,
            location=[Location(raw=loc_raw, country=country.upper())],
            type=item.get("contract_time"),
            salary=salary,
            descriptionText=html_to_text(item.get("description") or ""),
            applyUrl=url,
            canonicalUrl=url,
            postedAt=posted_at,
        ))
    return jobs


async def _get(country: str, params: dict) -> dict:
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise ConnectorError("Missing ADZUNA_APP_ID / ADZUNA_APP_KEY")

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    full_params = {"app_id": app_id, "app_key": app_key, "content-type": "application/json", **params}

    async with httpx.AsyncClient(timeout=15.0, headers=default_headers()) as client:
        response = await client.get(url, params=full_params)

    if response.status_code == 429 or response.status_code >= 500:
        raise ConnectorBackoffError(f"Adzuna ({country}) returned HTTP {response.status_code}")
    if response.status_code != 200:
        raise ConnectorError(f"Adzuna ({country}) returned HTTP {response.status_code}: {response.text[:200]}")

    try:
        return response.json()
    except ValueError:
        raise ConnectorError(f"Adzuna ({country}) returned non-JSON body")


async def search_by_keywords(
    titles: list[str], locations: list[str] | None = None, country: str = "us",
    remote_only: bool = False, max_results: int = 10,
) -> list[JobPosting]:
    """Free-text search for personalized automation (app/worker.py's personalized_discovery_task)
    -- unlike AdzunaConnector below, this isn't scoped to one company. `titles`/`locations` are
    OR'd together into Adzuna's own `what_or`/`where` params (Adzuna doesn't support multi-value
    location natively, so only the first location is sent; `what_or` does support multiple terms)."""
    params = {
        "what_or": " ".join(titles),
        "results_per_page": max_results,
    }
    if locations:
        params["where"] = locations[0]
    if remote_only:
        params["what_and"] = "remote"

    data = await _get(country, params)
    return _parse_results(data, country)


class AdzunaConnector(BaseConnector):
    """Queries Adzuna's job search aggregator (https://developer.adzuna.com), filtered to a
    single company via the `company` query param, rather than a company-hosted ATS board --
    Adzuna aggregates postings originally sourced from many ATSes and career sites, so this
    is a broad-net fallback (like ai_search) rather than a first-party board integration.
    Requires ADZUNA_APP_ID / ADZUNA_APP_KEY (free registration, no cost per the tier this
    project is on: https://developer.adzuna.com/signup)."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.country = (self.config.get("country") or "us").lower()

    async def fetch_jobs(self, etag=None):
        company = self.company_name or self.board_token
        if not company:
            self.status = ERROR
            raise ConnectorError("AdzunaConnector requires companyName or boardToken to filter by")

        try:
            data = await _get(self.country, {"company": company, "results_per_page": 50})
        except ConnectorBackoffError:
            self.status = ERROR
            raise
        except ConnectorError:
            self.status = ERROR
            raise

        jobs = _parse_results(data, self.country, fallback_company=company)
        self.status = SUCCESS_WITH_JOBS if jobs else SUCCESS_EMPTY
        return jobs
