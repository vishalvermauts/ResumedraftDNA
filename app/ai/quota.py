from datetime import datetime, timezone
from ..db.mongo import db

# Google's free grounded-prompt quota is 5,000/month for Gemini models on Vertex AI / Gemini API.
# We enforce a strict 96% circuit breaker (4,800 queries). Once reached, search grounding
# is completely locked out for the rest of the month, while all other standard AI services
# (chat, tailoring, cover letter, review) remain 100% active and running.
FREE_TIER_MONTHLY_LIMIT = 4800
TOTAL_FREE_QUOTA = 5000


def _month_key() -> str:
    return f"gemini_grounding_{datetime.now(timezone.utc).strftime('%Y-%m')}"


async def get_grounding_usage_count() -> int:
    try:
        doc = await db.db.api_usage_counters.find_one({"_id": _month_key()})
        return doc["count"] if doc and "count" in doc else 0
    except Exception:
        return 0


async def grounding_quota_available() -> bool:
    count = await get_grounding_usage_count()
    return count < FREE_TIER_MONTHLY_LIMIT


async def record_grounding_usage(increment: int = 1):
    try:
        await db.db.api_usage_counters.update_one(
            {"_id": _month_key()},
            {"$inc": {"count": increment}, "$set": {"lastUpdated": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
    except Exception as e:
        print(f"Failed to record grounding usage: {e}")


async def get_grounding_quota_status() -> dict:
    used = await get_grounding_usage_count()
    remaining = max(0, TOTAL_FREE_QUOTA - used)
    circuit_remaining = max(0, FREE_TIER_MONTHLY_LIMIT - used)
    is_locked = used >= FREE_TIER_MONTHLY_LIMIT
    percent_used = round((used / TOTAL_FREE_QUOTA) * 100, 1)

    return {
        "month": datetime.now(timezone.utc).strftime("%Y-%m"),
        "totalFreeQuota": TOTAL_FREE_QUOTA,
        "circuitBreakerCap": FREE_TIER_MONTHLY_LIMIT,
        "used": used,
        "remainingTotal": remaining,
        "remainingBeforeCutoff": circuit_remaining,
        "percentUsed": percent_used,
        "isCutoffActive": is_locked,
        "status": "locked" if is_locked else ("warning" if used >= 4000 else "ok")
    }

