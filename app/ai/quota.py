from datetime import datetime, timezone
from ..db.mongo import db

# Google's free grounded-prompt quota is ~5,000/month for the Gemini 3 family (shared across
# all callers on the project). Keep a buffer so we never actually cross into billed usage.
# Shared by connectors/ai_search.py (per-company) and worker.py's personalized_discovery_task
# (per-user role/location search) -- both draw from the same monthly bucket.
FREE_TIER_MONTHLY_LIMIT = 4500


def _month_key() -> str:
    return f"gemini_grounding_{datetime.now(timezone.utc).strftime('%Y-%m')}"


async def grounding_quota_available() -> bool:
    doc = await db.db.api_usage_counters.find_one({"_id": _month_key()})
    count = doc["count"] if doc else 0
    return count < FREE_TIER_MONTHLY_LIMIT


async def record_grounding_usage():
    await db.db.api_usage_counters.update_one(
        {"_id": _month_key()},
        {"$inc": {"count": 1}},
        upsert=True
    )
