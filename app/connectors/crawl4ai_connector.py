import asyncio
from typing import List
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from .base import BaseConnector, canonical_hash, html_to_text
from ..schemas.job import JobPosting, Location

class Crawl4AiConnector(BaseConnector):
    """Deep stealth headless crawler for complex single-page applications, 
    custom enterprise career portals (Workday, Taleo, custom React/Angular), 
    and user-submitted URLs."""

    async def fetch_jobs(self) -> List[JobPosting]:
        if not self.careers_url:
            return []

        browser_cfg = BrowserConfig(
            headless=True,
            verbose=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        run_cfg = CrawlerRunConfig(
            word_count_threshold=30,
            wait_until="domcontentloaded",
            delay_before_return_html=2.0
        )

        jobs = []
        try:
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                res = await crawler.arun(url=self.careers_url, config=run_cfg)
                if not res.success or not res.markdown:
                    return []

                markdown_content = res.markdown.strip()
                title = f"{self.company_name} Career Opportunities"
                h = canonical_hash("crawl4ai", self.company_name or "", self.careers_url, title, "Various", self.careers_url)

                jobs.append(JobPosting(
                    canonicalHash=h,
                    source="crawl4ai",
                    sourceJobId=self.careers_url,
                    companyName=self.company_name or "Company",
                    title=title,
                    location=[Location(raw="Australia / Global")],
                    descriptionText=markdown_content[:15000], # Keep high-density markdown context
                    applyUrl=self.careers_url,
                    canonicalUrl=self.careers_url,
                    status="active"
                ))
        except Exception as e:
            print(f"[Crawl4AiConnector] Error crawling {self.careers_url}: {e}")
            return []

        return jobs
