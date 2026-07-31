import httpx
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location

class GreenhouseConnector(BaseConnector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs"

    async def fetch_jobs(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}?content=true", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            jobs = []
            for job in data.get('jobs', []):
                # Normalize location
                offices = job.get('offices', [])
                loc_raw = offices[0].get('name') if offices else "Remote"
                
                # Create hash
                cid = self.board_token # Use token as company ID for now
                job_id = str(job.get('id'))
                h = canonical_hash("greenhouse", job_id, cid, job.get('title'), loc_raw, job.get('absolute_url'))
                
                jobs.append(JobPosting(
                    canonicalHash=h,
                    source="greenhouse",
                    sourceJobId=job_id,
                    companyName=self.board_token,
                    title=job.get('title'),
                    location=[Location(raw=loc_raw)],
                    descriptionText=job.get('content', ''),
                    applyUrl=job.get('absolute_url'),
                    canonicalUrl=job.get('absolute_url')
                ))
            return jobs
