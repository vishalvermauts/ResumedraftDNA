import asyncio
import re
from typing import List

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location


RESULT_RE = re.compile(
    r"###\s+\[(?P<title>[^\]]+)\]\((?P<url>https://www\.amazon\.jobs/en/jobs/\d+/[^)]+)\)(?P<body>.*?)(?=\n#{2,3}\s|$)",
    re.DOTALL,
)


def _default_search_query(company_name: str | None) -> str:
    if not company_name:
        return "amazon"
    cleaned = re.sub(r"\([^)]*\)", "", company_name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or company_name


def _extract_location(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line.lower() == "locations":
            for candidate in lines[idx + 1 : idx + 6]:
                if candidate.startswith("Job ID:") or candidate.startswith("Posted ") or candidate.startswith("Basic qualifications"):
                    continue
                cleaned = candidate.lstrip("* ").strip()
                if cleaned and cleaned != "|":
                    return cleaned
    return "Remote"


def _matches_location(location: str, targets: list[str] | None) -> bool:
    if not targets:
        return True
    loc = (location or "").lower()
    for target in targets:
        t = (target or "").strip().lower()
        if not t:
            continue
        if "all locations" in t:
            country = t.split("(", 1)[0].strip()
            if country and (country in loc or (country == "australia" and any(
                marker in loc for marker in (" aus", ", aus", "nsw", "vic", "qld", "wa", "sa", "tas", "act", "nt")
            ))):
                return True
            continue
        if t in loc:
            return True
        if t == "australia" and (" aus" in loc or ", aus" in loc or "nsw" in loc or "vic" in loc or "qld" in loc or "wa" in loc):
            return True
    return False


class AmazonJobsConnector(BaseConnector):
    """Amazon.jobs search connector.

    The Amazon.jobs site renders results into the page HTML/markdown rather than exposing a
    simple ATS JSON feed. We use crawl4ai to render the search results page and parse the
    job cards from the markdown output.
    """

    async def fetch_jobs(self) -> List[JobPosting]:
        if self.careers_url:
            url = self.careers_url
        else:
            query = _default_search_query(self.company_name)
            url = f"https://www.amazon.jobs/search?base_query={query.replace(' ', '+')}"

        browser_cfg = BrowserConfig(
            headless=True,
            verbose=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        run_cfg = CrawlerRunConfig(
            word_count_threshold=30,
            wait_until="domcontentloaded",
            delay_before_return_html=2.0,
        )

        try:
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                res = await crawler.arun(url=url, config=run_cfg)
        except Exception as exc:
            print(f"[AmazonJobsConnector] Error crawling {url}: {exc}")
            return []

        md = (res.markdown or "").strip()
        if not res.success or not md:
            return []

        jobs = []
        for match in RESULT_RE.finditer(md):
            title = match.group("title").strip()
            apply_url = match.group("url").strip()
            body = match.group("body")
            location = _extract_location(body)

            job_id_match = re.search(r"Job ID:\s*([0-9]+)", body)
            job_id = job_id_match.group(1) if job_id_match else apply_url

            description_parts = []
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("Posted ") or stripped.startswith("Job ID:") or stripped == "Locations":
                    continue
                if stripped.startswith("*"):
                    stripped = stripped.lstrip("* ").strip()
                if stripped and stripped != "|":
                    description_parts.append(stripped)
            description = "\n".join(description_parts[:30])

            h = canonical_hash("amazonjobs", job_id, self.company_name or "amazon", title, location, apply_url)
            jobs.append(JobPosting(
                canonicalHash=h,
                source="amazonjobs",
                sourceJobId=str(job_id),
                companyName=self.company_name or "Amazon",
                title=title,
                location=[Location(raw=location)],
                descriptionText=description[:15000],
                applyUrl=apply_url,
                canonicalUrl=apply_url,
                status="active",
            ))

        return jobs


async def search_by_keywords(titles: list[str], locations: list[str] | None = None, max_results: int = 10) -> list[JobPosting]:
    query = " ".join(titles).strip() or "amazon"
    url = f"https://www.amazon.jobs/search?base_query={query.replace(' ', '+')}"
    if locations:
      loc = locations[0].strip()
      if loc:
        url += f"&loc_query={loc.replace(' ', '+')}"

    browser_cfg = BrowserConfig(
        headless=True,
        verbose=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    )
    run_cfg = CrawlerRunConfig(
        word_count_threshold=30,
        wait_until="domcontentloaded",
        delay_before_return_html=2.0,
    )

    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            res = await crawler.arun(url=url, config=run_cfg)
    except Exception as exc:
        print(f"[AmazonJobsConnector] keyword search error for {url}: {exc}")
        return []

    md = (res.markdown or "").strip()
    if not res.success or not md:
        return []

    results = []
    for match in RESULT_RE.finditer(md):
        title = match.group("title").strip()
        apply_url = match.group("url").strip()
        body = match.group("body")
        location = _extract_location(body)
        if titles and not any(t.lower() in title.lower() for t in titles):
            continue
        if not _matches_location(location, locations):
            continue
        job_id_match = re.search(r"Job ID:\s*([0-9]+)", body)
        job_id = job_id_match.group(1) if job_id_match else apply_url
        description = "\n".join(
            line.strip().lstrip("* ").strip()
            for line in body.splitlines()
            if line.strip() and not line.startswith("Posted ") and not line.startswith("Job ID:") and line.strip() != "Locations"
        )
        h = canonical_hash("amazonjobs", job_id, "amazon", title, location, apply_url)
        results.append(JobPosting(
            canonicalHash=h,
            source="amazonjobs",
            sourceJobId=str(job_id),
            companyName="Amazon",
            title=title,
            location=[Location(raw=location)],
            descriptionText=description[:15000],
            applyUrl=apply_url,
            canonicalUrl=apply_url,
            status="active",
        ))
        if len(results) >= max_results:
            break

    return results
