from app.connectors.registry import get_connector


def test_search_grounding_connector_is_not_registered():
    """Grounding must be unavailable, not merely configured to return no jobs."""
    assert get_connector("ai_search", {"companyName": "example"}) is None
