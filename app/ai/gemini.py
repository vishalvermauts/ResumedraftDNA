import os
from google import genai
from google.genai import types
from pydantic import BaseModel

class GeminiClient:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    async def generate_structured(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
            )
        )
        return schema.model_validate_json(response.text)

    async def generate_grounded(self, prompt: str) -> str:
        """Gemini + Google Search grounding. Billed per search query beyond the free monthly
        quota -- callers must gate this behind their own quota check (see connectors/ai_search.py)."""
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        return response.text

gemini_client = GeminiClient()
