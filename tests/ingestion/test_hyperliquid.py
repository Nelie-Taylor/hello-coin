import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.hyperliquid import HYPERLIQUID_INFO_URL, HyperliquidAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0x1111111111111111111111111111111111111111"

FILL_RESPONSE = [
    {
        "coin": "BTC",
        "px": "60000.0",
        "sz": "2.5",
        "side": "B",
        "time": 1750000000000,
        "startPosition": "0.0",
        "dir": "Open Long",
        "closedPnl": "0.0",
        "hash": "0xabc123",
        "oid": 42,
        "crossed": True,
        "fee": "1.2",
        "tid": 999,
        "feeToken": "USDC",
    }
]


def test_is_configured_true_when_addresses_set():
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_addresses():
    settings = Settings(hyperliquid_watch_addresses=[])
    adapter = HyperliquidAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_fill_into_whale_event():
    respx.post(HYPERLIQUID_INFO_URL).mock(return_value=httpx.Response(200, json=FILL_RESPONSE))
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "hyperliquid"
    assert event.symbol == "BTC"
    assert event.side == "buy"
    assert event.amount == 2.5
    assert event.amount_usd == 150000.0
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xabc123:999"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_advances_start_time_on_second_call():
    route = respx.post(HYPERLIQUID_INFO_URL).mock(
        return_value=httpx.Response(200, json=FILL_RESPONSE)
    )
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    await adapter.fetch()
    await adapter.fetch()

    second_request_body = route.calls[1].request.content
    assert b'"startTime": 1750000000001' in second_request_body or b'"startTime":1750000000001' in second_request_body
