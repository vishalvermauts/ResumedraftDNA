from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import unicodedata


def canonical_company_id(company_name: str) -> str:
    """Return a stable, provider-independent identity for a company name."""
    value = unicodedata.normalize("NFKD", str(company_name or "")).encode(
        "ascii", "ignore"
    ).decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown-company"

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
            await self.db.ai_usage_events.create_index(
                [("uid", 1), ("createdAt", -1)], name="ai_usage_user_time"
            )
            await self.db.job_postings.create_index(
                [("companyId", 1), ("status", 1)], name="job_company_status"
            )
            await self.db.job_postings.create_index(
                [("freshnessAt", -1), ("discoveredAt", -1)], name="job_freshness"
            )
            await self.backfill_company_ids()
            await self.backfill_freshness_at()
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
            await self.backfill_company_ids()
            await self.backfill_freshness_at()
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
            ordered = await self.db.resume_snapshots.find(
                {"_id": {"$in": ids}}
            ).sort([
                ("active", -1), ("updatedAt", -1), ("createdAt", -1), ("_id", 1)
            ]).to_list(length=None)
            # Preserve the active/newest copy; identical content is immutable.
            for duplicate in ordered[1:]:
                duplicate_id = duplicate["_id"]
                await self.db.resume_snapshots.delete_one({"_id": duplicate_id})
        active_groups = await self.db.resume_snapshots.aggregate([
            {"$match": {"uid": {"$exists": True}, "active": True}},
            {"$group": {"_id": "$uid", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
        ]).to_list(length=None)
        for group in active_groups:
            ids = group.get("ids") or []
            ordered = await self.db.resume_snapshots.find(
                {"_id": {"$in": ids}}
            ).sort([
                ("updatedAt", -1), ("createdAt", -1), ("_id", 1)
            ]).to_list(length=None)
            for duplicate in ordered[1:]:
                await self.db.resume_snapshots.update_one(
                    {"_id": duplicate["_id"]}, {"$set": {"active": False}}
                )

    async def close(self):
        self.client.close()
    
    async def upsert_job(self, job_data):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        job_data["companyId"] = job_data.get("companyId") or canonical_company_id(
            job_data.get("companyName")
        )
        # `discoveredAt` is first-seen provenance, not a polling heartbeat. Do
        # not overwrite it when a connector sees the same posting again.
        first_seen = job_data.pop("discoveredAt", None) or now
        job_data["lastSeenAt"] = now
        job_data["missedPolls"] = 0
        job_data["status"] = "active"
        job_data["freshnessAt"] = job_data.get("postedAt") or first_seen
        return await self.db.job_postings.update_one(
            {"canonicalHash": job_data["canonicalHash"]},
            {"$set": job_data, "$setOnInsert": {"discoveredAt": first_seen}},
            upsert=True
        )

    async def mark_source_empty(self, company_name: str, source: str, now, stale_after: int = 2, company_id: str | None = None):
        """Advance stale detection only after a healthy empty provider response.

        An empty feed cannot prove a role was filled, so this deliberately marks
        postings stale rather than filled. A later observation reactivates them
        through ``upsert_job``.
        """
        company_id = company_id or canonical_company_id(company_name)
        match = {
            "$or": [{"companyId": company_id}, {"companyName": company_name}],
            "source": source,
            "status": {"$in": ["active", "stale"]},
        }
        await self.db.job_postings.update_many(
            match,
            {"$inc": {"missedPolls": 1}, "$set": {"lastPollAt": now}},
        )
        await self.db.job_postings.update_many(
            {**match, "missedPolls": {"$gte": stale_after}},
            {"$set": {"status": "stale", "staleSince": now}},
        )

    async def mark_source_closed(self, company_name: str, source: str, source_job_ids, now, company_id: str | None = None):
        """Mark only provider-confirmed closed postings as filled."""
        ids = [str(value) for value in (source_job_ids or []) if value is not None]
        if not ids:
            return
        company_id = company_id or canonical_company_id(company_name)
        await self.db.job_postings.update_many(
            {
                "$or": [{"companyId": company_id}, {"companyName": company_name}],
                "source": source,
                "sourceJobId": {"$in": ids},
                "status": {"$nin": ["filled", "expired"]},
            },
            {"$set": {"status": "filled", "filledAt": now}},
        )

    async def expire_deadline_jobs(self, now):
        """Transition passed application deadlines without overriding filled jobs."""
        return await self.db.job_postings.update_many(
            {
                "applicationDeadline": {"$lte": now},
                "status": {"$nin": ["filled", "expired"]},
            },
            {"$set": {"status": "expired", "expiredAt": now}},
        )

    async def backfill_company_ids(self):
        """Backfill stable company identities on legacy normalized job records."""
        updated = 0
        cursor = self.db.job_postings.find(
            {"$or": [{"companyId": {"$exists": False}}, {"companyId": None}, {"companyId": ""}]},
            {"_id": 1, "companyName": 1},
        )
        async for job in cursor:
            result = await self.db.job_postings.update_one(
                {"_id": job["_id"], "$or": [{"companyId": {"$exists": False}}, {"companyId": None}, {"companyId": ""}]},
                {"$set": {"companyId": canonical_company_id(job.get("companyName"))}},
            )
            updated += result.modified_count
        return updated

    async def backfill_freshness_at(self):
        """Populate the effective freshness timestamp for legacy job records."""
        updated = 0
        cursor = self.db.job_postings.find(
            {"freshnessAt": {"$exists": False}},
            {"_id": 1, "postedAt": 1, "discoveredAt": 1},
        )
        async for job in cursor:
            freshness = job.get("postedAt") or job.get("discoveredAt")
            if freshness is None:
                continue
            result = await self.db.job_postings.update_one(
                {"_id": job["_id"], "freshnessAt": {"$exists": False}},
                {"$set": {"freshnessAt": freshness}},
            )
            updated += result.modified_count
        return updated

db = Database()
