import json

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

POSITION_RESPONSE = {
    "assetPositions": [
        {
            "position": {
                "coin": "BTC",
                "szi": "2.5",
                "positionValue": "150000.0",
                "leverage": {"type": "cross", "value": 7},
            }
        }
    ]
}


def _info_response(request: httpx.Request) -> httpx.Response:
    request_type = json.loads(request.content)["type"]
    if request_type == "userFillsByTime":
        return httpx.Response(200, json=FILL_RESPONSE)
    if request_type == "clearinghouseState":
        return httpx.Response(200, json=POSITION_RESPONSE)
    raise AssertionError(f"Unexpected Hyperliquid request type: {request_type}")


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
    respx.post(HYPERLIQUID_INFO_URL).mock(side_effect=_info_response)
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    events = await adapter.fetch()

    event = next(event for event in events if event.event_type == "fill")
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
    route = respx.post(HYPERLIQUID_INFO_URL).mock(side_effect=_info_response)
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    await adapter.fetch()
    await adapter.fetch()

    second_request_body = route.calls[2].request.content
    assert b'"startTime": 1750000000001' in second_request_body or b'"startTime":1750000000001' in second_request_body


@pytest.mark.asyncio
@respx.mock
async def test_fetch_records_open_position_with_actual_leverage_separately_from_fill():
    respx.post(HYPERLIQUID_INFO_URL).mock(side_effect=_info_response)
    adapter = HyperliquidAdapter(Settings(hyperliquid_watch_addresses=[ADDRESS]))

    events = await adapter.fetch()

    fill = next(event for event in events if event.event_type == "fill")
    position = next(event for event in events if event.event_type == "position")
    assert "leverage" not in fill.raw
    assert position.symbol == "BTC"
    assert position.side == "buy"
    assert position.amount == 2.5
    assert position.amount_usd == 150000.0
    assert position.raw["leverage"]["value"] == 7
