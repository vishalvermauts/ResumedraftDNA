import os
import subprocess
from google import genai
from google.genai import types
import google.auth.credentials
from pydantic import BaseModel


class StaticTokenCredentials(google.auth.credentials.Credentials):
    def __init__(self, token):
        super().__init__()
        self.token = token

    def refresh(self, request):
        pass

    def apply(self, headers, token=None):
        headers["authorization"] = f"Bearer {self.token}"

    def before_request(self, request, method, url, headers):
        headers["authorization"] = f"Bearer {self.token}"


def _get_auth_client():
    use_vertex = os.getenv("USE_VERTEX_AI", "true").lower() == "true"
    if use_vertex:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "resumedraft")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        # 1. Try local gcloud token with StaticTokenCredentials
        try:
            token = subprocess.check_output("gcloud auth print-access-token", shell=True).decode().strip()
            if token.startswith("ya29."):
                creds = StaticTokenCredentials(token)
                return genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        except Exception:
            pass

        # 2. Try default ADC (works in Google Cloud environments)
        try:
            return genai.Client(vertexai=True, project=project, location=location)
        except Exception:
            pass

        return genai.Client(vertexai=True, project=project, location=location)

    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class GeminiClient:
    def __init__(self):
        self.client = _get_auth_client()
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    async def generate_structured(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        feature: str = "resume_tailor",
        thinking_level: str = "low"
    ) -> BaseModel:
        labels = {"feature": feature, "app": "resumedraft"}
        config_kwargs = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "labels": labels,
        }
        
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs)
        )
        return schema.model_validate_json(response.text)

    async def generate_grounded(self, prompt: str, feature: str = "search_grounding") -> str:
        """Gemini + Google Search grounding. Quota-guarded to stop at 4,800/5,000 queries."""
        if os.getenv("ENABLE_GEMINI_GROUNDING", "false").lower() != "true":
            raise RuntimeError("Gemini grounding is disabled by ENABLE_GEMINI_GROUNDING")
        labels = {"feature": feature, "app": "resumedraft"}
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                labels=labels,
            )
        )
        return response.text

gemini_client = GeminiClient()

