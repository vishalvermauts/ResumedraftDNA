import os
import subprocess
import asyncio
import time
from google import genai
from google.genai import types
import google.auth.credentials
from pydantic import BaseModel
from .usage import record_ai_usage


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
        # Firebase emulator namespace and Vertex billing project are independent.
        project = os.getenv("VERTEX_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "resumedraft"))
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

        try:
            return genai.Client(vertexai=True, project=project, location=location)
        except Exception:
            pass

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            return genai.Client(api_key=api_key)
        except Exception:
            pass
    return None


class GeminiClient:
    def __init__(self):
        try:
            self.client = _get_auth_client()
        except Exception:
            self.client = None
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    async def _generate_via_helix(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_output_tokens: int = 8192,
    ) -> tuple[BaseModel, dict]:
        import httpx
        key = os.getenv("HELIX_GATEWAY_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("HELIX_GATEWAY_BASE_URL", "https://router.helixengine.app").rstrip("/")
        model = os.getenv("HELIX_MODEL", "gemini-pro")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": min(max_output_tokens, 4096),
            "temperature": 0.2
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = schema.model_validate_json(content)
            usage = data.get("usage") or {}
            usage_dict = {
                "promptTokenCount": usage.get("prompt_tokens"),
                "candidatesTokenCount": usage.get("completion_tokens"),
                "totalTokenCount": usage.get("total_tokens"),
            }
            return parsed, usage_dict

    async def generate_structured(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        feature: str = "resume_tailor",
        thinking_level: str = "low",
        max_output_tokens: int = 8192,
        uid: str | None = None,
    ) -> BaseModel:
        config_kwargs = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "max_output_tokens": max_output_tokens,
        }
        # Gemini Developer API rejects Vertex Agent Platform-only labels.
        # Keep labels only when the local/production client is explicitly Vertex-backed.
        if os.getenv("USE_VERTEX_AI", "true").lower() == "true":
            config_kwargs["labels"] = {"feature": feature, "app": "resumedraft"}
        
        last_error = None
        started_at = time.perf_counter()
        provider = "vertex_ai" if os.getenv("USE_VERTEX_AI", "true").lower() == "true" else "gemini_api"
        for attempt in range(3):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user,
                    config=types.GenerateContentConfig(**config_kwargs)
                )
                candidate = (getattr(response, "candidates", None) or [None])[0]
                finish_reason = getattr(candidate, "finish_reason", None)
                if finish_reason is not None and str(finish_reason).upper().endswith("MAX_TOKENS"):
                    raise ValueError("Vertex structured generation was truncated: MAX_TOKENS")
                if not getattr(response, "text", None):
                    raise ValueError("Vertex structured generation returned no text")
                # Parsing is part of a successful provider response. Keeping it
                # inside the retry boundary lets a malformed JSON candidate be
                # regenerated instead of crashing a whole certification run.
                parsed_response = schema.model_validate_json(response.text)
                usage = getattr(response, "usage_metadata", None)
                usage_dict = {
                    "promptTokenCount": getattr(usage, "prompt_token_count", None),
                    "candidatesTokenCount": getattr(usage, "candidates_token_count", None),
                    "totalTokenCount": getattr(usage, "total_token_count", None),
                } if usage else {}
                await record_ai_usage(
                    uid=uid, feature=feature, model=self.model, provider=provider,
                    usage_metadata=usage_dict, duration_ms=(time.perf_counter() - started_at) * 1000,
                )
                return parsed_response
            except Exception as error:
                last_error = error
                # Fallback to HelixGateway if configured
                helix_key = os.getenv("HELIX_GATEWAY_KEY") or os.getenv("OPENAI_API_KEY")
                if helix_key:
                    try:
                        parsed_response, usage_dict = await self._generate_via_helix(
                            system=system, user=user, schema=schema, max_output_tokens=max_output_tokens
                        )
                        helix_model = os.getenv("HELIX_MODEL", "gemini-pro")
                        await record_ai_usage(
                            uid=uid, feature=feature, model=helix_model, provider="helixgateway",
                            usage_metadata=usage_dict, duration_ms=(time.perf_counter() - started_at) * 1000,
                        )
                        return parsed_response
                    except Exception as h_err:
                        last_error = h_err
                if attempt == 2:
                    await record_ai_usage(
                        uid=uid, feature=feature, model=self.model, provider=provider,
                        status="failed", error_code=type(error).__name__,
                        duration_ms=(time.perf_counter() - started_at) * 1000,
                    )
                    raise
                await asyncio.sleep(2 ** attempt)
        return parsed_response

    async def generate_grounded(self, prompt: str, feature: str = "search_grounding") -> str:
        raise RuntimeError("Gemini grounding is permanently disabled")

gemini_client = GeminiClient()
