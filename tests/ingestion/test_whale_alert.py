import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.whale_alert import (
    WHALE_ALERT_TRANSACTIONS_URL,
    WhaleAlertAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

TRANSACTIONS_RESPONSE = {
    "result": "success",
    "cursor": "abc",
    "count": 1,
    "transactions": [
        {
            "blockchain": "ethereum",
            "symbol": "usdt",
            "id": 123456,
            "transaction_type": "transfer",
            "hash": "0xabc123",
            "from": {"address": "0x1111111111111111111111111111111111111111", "owner": "binance"},
            "to": {"address": "0x2222222222222222222222222222222222222222", "owner": "unknown"},
            "timestamp": 1787372700,
            "amount": 5_000_000.0,
            "amount_usd": 5_000_000.0,
            "transaction_count": 1,
        }
    ],
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(whale_alert_api_key="test-key")
    adapter = WhaleAlertAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(whale_alert_api_key=None)
    adapter = WhaleAlertAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transaction_into_whale_event():
    respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(whale_alert_api_key="test-key", whale_alert_min_value_usd=500_000)
    adapter = WhaleAlertAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "whale_alert"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "usdt"
    assert event.event_type == "transfer"
    assert event.amount == 5_000_000.0
    assert event.amount_usd == 5_000_000.0
    assert event.wallet_address == "0x2222222222222222222222222222222222222222"
    assert event.dedup_key == "0xabc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_api_key_and_min_value_params():
    route = respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(whale_alert_api_key="test-key", whale_alert_min_value_usd=1_000_000)
    adapter = WhaleAlertAdapter(settings)

    await adapter.fetch()

    params = route.calls[0].request.url.params
    assert params["api_key"] == "test-key"
    assert params["min_value"] == "1000000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_skips_transactions_missing_expected_fields():
    malformed_response = {
        "result": "success",
        "cursor": "abc",
        "count": 1,
        "transactions": [{"blockchain": "ethereum", "symbol": "usdt"}],
    }
    respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=malformed_response)
    )
    settings = Settings(whale_alert_api_key="test-key")
    adapter = WhaleAlertAdapter(settings)

    events = await adapter.fetch()

    assert events == []
