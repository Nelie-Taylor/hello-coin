import json

import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.nansen import NANSEN_TRANSACTIONS_URL, NansenAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

TRANSACTIONS_RESPONSE = {
    "pagination": {"page": 1, "per_page": 100, "total": 1},
    "data": [
        {
            "chain": "ethereum",
            "method": "transfer",
            "tokens_sent": [
                {
                    "token_symbol": "USDC",
                    "token_amount": "150000.0",
                    "price_usd": "1.0",
                    "value_usd": "150000.0",
                    "token_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "chain": "ethereum",
                    "from_address": ADDRESS,
                    "to_address": "0x2222222222222222222222222222222222222222",
                    "from_address_label": "Whale Wallet",
                    "to_address_label": None,
                }
            ],
            "tokens_received": [],
            "volume_usd": "150000.0",
            "block_timestamp": "2026-08-21T12:00:00Z",
            "transaction_hash": "0xabc123",
            "source_type": "dex",
        }
    ],
}


def test_is_configured_true_when_key_and_addresses_set():
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_key():
    settings = Settings(nansen_api_key=None, nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transaction_into_whale_event():
    respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "nansen"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "USDC"
    assert event.event_type == "transfer"
    assert event.side == "sell"
    assert event.amount == 150000.0
    assert event.amount_usd == 150000.0
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xabc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_apikey_header_and_documented_body_fields():
    route = respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    await adapter.fetch()

    request = route.calls[0].request
    assert request.headers["apikey"] == "test-key"
    body = json.loads(request.content)
    assert body["address"] == ADDRESS
    assert body["chain"] == "ethereum"
    assert "date" in body


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_transactions():
    empty_response = {"pagination": {"page": 1, "per_page": 100, "total": 0}, "data": []}
    respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    events = await adapter.fetch()

    assert events == []
