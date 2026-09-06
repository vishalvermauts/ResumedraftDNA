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
        # Enforce snapshot identity and one active master per user at the
        # database boundary, including concurrent import requests.
        try:
            await self.db.resume_snapshots.create_index(
                [("uid", 1), ("contentHash", 1)], unique=True,
                name="resume_snapshot_identity",
            )
            await self.db.resume_snapshots.create_index(
                [("uid", 1)], unique=True,
                partialFilterExpression={"active": True},
                name="one_active_master_per_user",
            )
        except Exception as error:
            # Existing legacy duplicates are reported for migration rather
            # than preventing unrelated API endpoints from starting.
            print(f"Snapshot index migration warning: {error}")
        print("Connected to MongoDB")

    async def close(self):
        self.client.close()
    
    async def upsert_job(self, job_data):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        job_data["lastSeenAt"] = now
        job_data["missedPolls"] = 0
        job_data["status"] = "active"
        return await self.db.job_postings.update_one(
            {"canonicalHash": job_data["canonicalHash"]},
            {"$set": job_data},
            upsert=True
        )

db = Database()
