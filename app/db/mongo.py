from motor.motor_asyncio import AsyncIOMotorClient
import os

class Database:
    client: AsyncIOMotorClient = None
    db = None

    async def connect(self):
        # Use provided env or default
        uri = os.getenv("MONGODB_URI", "mongodb://mongo:27017/resumedraft")
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client.get_database() # Uses the database name from URI
        print("Connected to MongoDB")

    async def close(self):
        self.client.close()
    
    async def upsert_job(self, job_data):
        # Canonical upsert
        return await self.db.job_postings.update_one(
            {"canonicalHash": job_data["canonicalHash"]},
            {"$set": job_data},
            upsert=True
        )

db = Database()
