import httpx
import asyncio

async def test_greenhouse_connector():
    # Public board token for a known company (Canva)
    board_token = "stripe"
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            jobs = data.get('jobs', [])
            print(f"Successfully fetched {len(jobs)} jobs from {board_token}")
            if jobs:
                print("First job sample:")
                job = jobs[0]
                print(f"- Title: {job.get('title')}")
                print(f"- Company: {job.get('offices', [{}])[0].get('name') if job.get('offices') else 'N/A'}")
                print(f"- URL: {job.get('absolute_url')}")
        except Exception as e:
            print(f"Error fetching Greenhouse jobs: {e}")

if __name__ == "__main__":
    asyncio.run(test_greenhouse_connector())
