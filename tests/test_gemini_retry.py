from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel


class _ResponseModel(BaseModel):
    value: str


class _FakeModels:
    def __init__(self):
        self.calls = 0

    async def generate_content(self, **_kwargs):
        self.calls += 1
        text = '{bad json' if self.calls == 1 else '{"value":"recovered"}'
        return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason="STOP")], usage_metadata=None)


async def test_structured_generation_retries_malformed_json_before_returning():
    """A syntactically invalid Vertex response is a provider failure, not a pass."""
    from app.ai.gemini import GeminiClient

    client = GeminiClient.__new__(GeminiClient)
    client.model = "test-model"
    models = _FakeModels()
    client.client = SimpleNamespace(aio=SimpleNamespace(models=models))

    with patch("app.ai.gemini.record_ai_usage", new=AsyncMock()), patch("app.ai.gemini.asyncio.sleep", new=AsyncMock()):
        result = await client.generate_structured("system", "user", _ResponseModel)

    assert result.value == "recovered"
    assert models.calls == 2
