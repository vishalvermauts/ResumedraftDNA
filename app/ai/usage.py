"""Server-side AI usage ledger.

Only operational metadata is stored. Prompts, resume text, and model output are
intentionally excluded so observability cannot become a second content store.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from ..db.mongo import db


def _number(value):
    return int(value) if value is not None else None


async def record_ai_usage(*, uid, feature, model, provider, usage_metadata=None,
                         status="success", duration_ms=0, error_code=None):
    usage_metadata = usage_metadata or {}
    input_tokens = _number(usage_metadata.get("promptTokenCount"))
    output_tokens = _number(usage_metadata.get("candidatesTokenCount"))
    total_tokens = _number(usage_metadata.get("totalTokenCount"))
    input_rate = float(os.getenv("VERTEX_INPUT_USD_PER_MILLION", "0"))
    output_rate = float(os.getenv("VERTEX_OUTPUT_USD_PER_MILLION", "0"))
    estimated_cost = None
    if input_tokens is not None and output_tokens is not None and (input_rate or output_rate):
        estimated_cost = round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)

    event = {
        "requestId": str(uuid4()),
        "uid": uid,
        "feature": feature,
        "provider": provider,
        "model": model,
        "groundingUsed": False,
        "status": status,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUsd": estimated_cost,
        "pricingConfigured": bool(input_rate or output_rate),
        "durationMs": int(duration_ms),
        "errorCode": error_code,
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        if db.db is not None:
            await db.db.ai_usage_events.insert_one(event)
    except Exception as exc:
        # Observability must never turn a successful AI request into a user error.
        print(f"AI usage ledger write failed: {exc}")
