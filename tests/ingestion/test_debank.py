import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.debank import DEBANK_TOTAL_BALANCE_URL, DebankAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

BALANCE_RESPONSE = {
    "total_usd_value": 27654.142997146177,
    "chain_list": [
        {
            "id": "eth",
            "community_id": 1,
            "name": "Ethereum",
            "native_token_id": "eth",
            "logo_url": "https://static.debank.com/image/chain/logo_url/eth/x.png",
            "wrapped_token_id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "usd_value": 11937.702345945296,
        }
    ],
}


def test_is_configured_true_when_key_and_addresses_set():
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_key():
    settings = Settings(debank_access_key=None, debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_total_balance_into_position_event():
    respx.get(DEBANK_TOTAL_BALANCE_URL).mock(
        return_value=httpx.Response(200, json=BALANCE_RESPONSE)
    )
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "debank"
    assert event.event_type == "position"
    assert event.side is None
    assert event.symbol == "USD"
    assert event.amount == pytest.approx(27654.142997146177)
    assert event.amount_usd == pytest.approx(27654.142997146177)
    assert event.wallet_address == ADDRESS
    assert event.dedup_key.startswith(f"{ADDRESS}:")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_access_key_header():
    route = respx.get(DEBANK_TOTAL_BALANCE_URL).mock(
        return_value=httpx.Response(200, json=BALANCE_RESPONSE)
    )
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["AccessKey"] == "test-key"
    assert route.calls[0].request.url.params["id"] == ADDRESS
