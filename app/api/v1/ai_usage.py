from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from ...auth import get_current_user
from ...db.mongo import db

router = APIRouter()


@router.get("/ai-usage")
async def get_ai_usage(
    since: datetime | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Return privacy-preserving AI usage totals for the authenticated user."""
    start = since or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    pipeline = [
        {"$match": {"uid": user["uid"], "createdAt": {"$gte": start}}},
        {"$group": {
            "_id": "$feature",
            "calls": {"$sum": 1},
            "successfulCalls": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
            "inputTokens": {"$sum": {"$ifNull": ["$inputTokens", 0]}},
            "outputTokens": {"$sum": {"$ifNull": ["$outputTokens", 0]}},
            "totalTokens": {"$sum": {"$ifNull": ["$totalTokens", 0]}},
            "estimatedCostUsd": {"$sum": {"$ifNull": ["$estimatedCostUsd", 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.db.ai_usage_events.aggregate(pipeline).to_list(length=100)
    features = [{
        "feature": row.get("_id"),
        "calls": row.get("calls", 0),
        "successfulCalls": row.get("successfulCalls", 0),
        "inputTokens": row.get("inputTokens", 0),
        "outputTokens": row.get("outputTokens", 0),
        "totalTokens": row.get("totalTokens", 0),
        "estimatedCostUsd": round(row.get("estimatedCostUsd", 0), 8),
        "groundingUsed": False,
    } for row in rows]
    return {
        "since": start.isoformat(),
        "groundingUsed": False,
        "features": features,
        "totals": {
            "calls": sum(row["calls"] for row in features),
            "successfulCalls": sum(row["successfulCalls"] for row in features),
            "inputTokens": sum(row["inputTokens"] for row in features),
            "outputTokens": sum(row["outputTokens"] for row in features),
            "totalTokens": sum(row["totalTokens"] for row in features),
            "estimatedCostUsd": round(sum(row["estimatedCostUsd"] for row in features), 8),
        },
    }
