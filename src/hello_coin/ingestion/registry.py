import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.hyperdash import HyperdashAdapter
from hello_coin.ingestion.config import Settings

logger = logging.getLogger(__name__)


def build_adapters(settings: Settings) -> list[Adapter]:
    """Return every adapter that reports itself as configured, logging a
    warning for each one that's skipped."""

    candidates: list[Adapter] = [HyperdashAdapter(settings)]

    configured: list[Adapter] = []
    for adapter in candidates:
        if adapter.is_configured():
            configured.append(adapter)
        else:
            logger.warning("%s: not configured, skipping", adapter.name)
    return configured
