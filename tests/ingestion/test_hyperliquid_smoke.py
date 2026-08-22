import pytest

from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

# A syntactically valid but arbitrary address — Hyperliquid's public info endpoint
# returns an empty fills list for an address with no history rather than erroring,
# so this only asserts the real API is reachable and the response parses cleanly.
PLACEHOLDER_ADDRESS = "0x" + "0" * 40


@pytest.mark.network
@pytest.mark.asyncio
async def test_fetch_reaches_real_hyperliquid_api():
    settings = Settings(hyperliquid_watch_addresses=[PLACEHOLDER_ADDRESS])
    adapter = HyperliquidAdapter(settings)

    events = await adapter.fetch()

    assert isinstance(events, list)
    assert all(isinstance(event, WhaleEvent) for event in events)
