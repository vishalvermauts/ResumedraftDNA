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
            # Older deployments could create duplicate snapshots before the
            # unique constraint existed. Repair identical content records,
            # then retry so the integrity guarantee is real, not advisory.
            print(f"Snapshot index migration warning; attempting duplicate repair: {error}")
            await self._repair_snapshot_duplicates()
            await self.db.resume_snapshots.create_index(
                [("uid", 1), ("contentHash", 1)], unique=True,
                name="resume_snapshot_identity",
            )
            await self.db.resume_snapshots.create_index(
                [("uid", 1)], unique=True,
                partialFilterExpression={"active": True},
                name="one_active_master_per_user",
            )
        print("Connected to MongoDB")

    async def _repair_snapshot_duplicates(self):
        """Keep one copy of identical legacy snapshots before unique indexing."""
        pipeline = [
            {"$match": {"uid": {"$exists": True}, "contentHash": {"$exists": True}}},
            {"$group": {
                "_id": {"uid": "$uid", "contentHash": "$contentHash"},
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ]
        duplicates = await self.db.resume_snapshots.aggregate(pipeline).to_list(length=None)
        for group in duplicates:
            ids = group.get("ids") or []
            # Preserve the first document; identical content is immutable and
            # active selection is handled separately by the active index.
            for duplicate_id in ids[1:]:
                await self.db.resume_snapshots.delete_one({"_id": duplicate_id})
        active_groups = await self.db.resume_snapshots.aggregate([
            {"$match": {"uid": {"$exists": True}, "active": True}},
            {"$group": {"_id": "$uid", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
        ]).to_list(length=None)
        for group in active_groups:
            for duplicate_id in (group.get("ids") or [])[1:]:
                await self.db.resume_snapshots.update_one(
                    {"_id": duplicate_id}, {"$set": {"active": False}}
                )

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
