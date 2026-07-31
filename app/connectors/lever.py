import httpx
from .base import BaseConnector, canonical_hash
from ..schemas.job import JobPosting, Location

class LeverConnector(BaseConnector):
    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = f"https://api.lever.co/v0/postings/{self.board_token}?mode=json"

    async def fetch_jobs(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(self.base_url, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            jobs = []
            for job in data:
                loc_raw = job.get('categories', {}).get('location', 'Remote')
                
                # Create hash
                cid = self.board_token
                job_id = job.get('id')
                h = canonical_hash("lever", job_id, cid, job.get('text'), loc_raw, job.get('hostedUrl'))
                
                jobs.append(JobPosting(
                    canonicalHash=h,
                    source="lever",
                    sourceJobId=job_id,
                    companyName=cid,
                    title=job.get('text'),
                    location=[Location(raw=loc_raw)],
                    descriptionText=job.get('descriptionPlain', ''),
                    applyUrl=job.get('hostedUrl'),
                    canonicalUrl=job.get('hostedUrl')
                ))
            return jobs
