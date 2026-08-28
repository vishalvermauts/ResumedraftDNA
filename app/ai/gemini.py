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

        # Local certification can inject a short-lived gcloud access token without
        # storing a private key in the repository. Production continues to use ADC.
        access_token = os.getenv("VERTEX_ACCESS_TOKEN")
        if access_token:
            return genai.Client(
                vertexai=True,
                project=project,
                location=location,
                credentials=StaticTokenCredentials(access_token),
            )

        # 1. Try default ADC / workload identity / service-account-based auth first.
        try:
            return genai.Client(vertexai=True, project=project, location=location)
        except Exception:
            pass

        # 2. Try local gcloud token only for interactive developer sessions.
        if os.getenv("CI", "").lower() not in ("true", "1", "yes"):
            try:
                token = subprocess.check_output("gcloud auth print-access-token", shell=True).decode().strip()
                if token.startswith("ya29."):
                    creds = StaticTokenCredentials(token)
                    return genai.Client(vertexai=True, project=project, location=location, credentials=creds)
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
        config_kwargs = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        # Gemini Developer API rejects Vertex Agent Platform-only labels.
        # Keep labels only when the local/production client is explicitly Vertex-backed.
        if os.getenv("USE_VERTEX_AI", "true").lower() == "true":
            config_kwargs["labels"] = {"feature": feature, "app": "resumedraft"}
        
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs)
        )
        return schema.model_validate_json(response.text)

    async def generate_grounded(self, prompt: str, feature: str = "search_grounding") -> str:
        raise RuntimeError("Gemini grounding is permanently disabled")

gemini_client = GeminiClient()
