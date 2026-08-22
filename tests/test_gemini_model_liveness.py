"""
Model-liveness smoke test.

This is the cheapest, highest-value test in the release gate: it would have caught the
gemini-2.0-flash deprecation (every /v1/tailor call 500'd for an unknown period before this
was diagnosed) before a single line of application code needed to change, by simply confirming
the configured model still exists and is servable.

Run in CI on every PR. Requires GEMINI_API_KEY -- skipped (not failed) when absent, so it
doesn't block local development without a key.
"""
import os
import pytest
from google import genai

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; skipping live model check"
)


def _configured_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


def test_configured_model_exists_and_is_accessible():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model_name = _configured_model()
    try:
        model = client.models.get(model=model_name)
    except Exception as e:
        pytest.fail(
            f"Configured Gemini model '{model_name}' is not accessible: {e}. "
            f"It may have been deprecated/retired -- check available models and update "
            f"GEMINI_MODEL / the default in app/ai/gemini.py."
        )
    assert model is not None


def test_configured_model_supports_generate_content():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model_name = _configured_model()
    model = client.models.get(model=model_name)
    supported = getattr(model, "supported_actions", None) or []
    assert "generateContent" in supported, (
        f"Model '{model_name}' exists but does not support generateContent "
        f"(supported actions: {supported}) -- the app calls generate_content directly."
    )


def test_search_grounding_is_disabled_by_default():
    assert os.getenv("ENABLE_GEMINI_GROUNDING", "false").lower() != "true", (
        "Search grounding must remain disabled in all test and production environments."
    )
