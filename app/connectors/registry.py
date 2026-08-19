from .greenhouse import GreenhouseConnector
from .lever import LeverConnector
from .jsonld import JsonLdConnector
from .ai_search import AiSearchConnector
from .ashby import AshbyConnector
from .recruitee import RecruiteeConnector
from .smartrecruiters import SmartRecruitersConnector
from .adzuna import AdzunaConnector
from .crawl4ai_connector import Crawl4AiConnector

# Adding a new job source = write one connector class implementing fetch_jobs(), add one line
# here. No changes needed in scout.py or worker.py's polling loop.
CONNECTOR_REGISTRY = {
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "jsonld": JsonLdConnector,
    "ai_search": AiSearchConnector,
    "ashby": AshbyConnector,
    "recruitee": RecruiteeConnector,
    "smartrecruiters": SmartRecruitersConnector,
    "adzuna": AdzunaConnector,
    "crawl4ai": Crawl4AiConnector,
}


def get_connector(connector_type: str, config: dict):
    cls = CONNECTOR_REGISTRY.get(connector_type)
    if not cls:
        return None
    return cls(config)
