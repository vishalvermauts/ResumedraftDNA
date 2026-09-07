from datetime import datetime, timezone


async def test_ai_usage_is_user_scoped_and_does_not_return_content(client):
    from app.db.mongo import db

    await db.db.ai_usage_events.insert_many([
        {
            "uid": "test-uid-12345", "feature": "resume_tailor", "status": "success",
            "inputTokens": 100, "outputTokens": 25, "totalTokens": 125,
            "estimatedCostUsd": 0.0012, "groundingUsed": False,
            "createdAt": datetime.now(timezone.utc), "prompt": "must not be returned",
        },
        {
            "uid": "other-user", "feature": "cover_letter", "status": "success",
            "inputTokens": 999, "outputTokens": 999, "totalTokens": 1998,
            "estimatedCostUsd": 9.0, "groundingUsed": False,
            "createdAt": datetime.now(timezone.utc),
        },
    ])

    response = await client.get("/v1/ai-usage")
    assert response.status_code == 200
    body = response.json()
    assert body["groundingUsed"] is False
    assert body["totals"]["totalTokens"] == 125
    assert body["totals"]["estimatedCostUsd"] == 0.0012
    assert body["features"][0]["feature"] == "resume_tailor"
    assert "prompt" not in body
