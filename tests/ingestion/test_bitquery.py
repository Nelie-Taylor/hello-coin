import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bitquery import BITQUERY_GRAPHQL_URL, BitqueryAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

TRANSFERS_RESPONSE = {
    "data": {
        "EVM": {
            "Transfers": [
                {
                    "Transfer": {
                        "Amount": "12.5",
                        "AmountInUSD": "875000.0",
                        "Currency": {
                            "Fungible": True,
                            "Name": "Wrapped Ether",
                            "ProtocolName": None,
                            "Symbol": "WETH",
                        },
                        "Sender": "0x1111111111111111111111111111111111111111",
                        "Receiver": "0x2222222222222222222222222222222222222222",
                        "Success": True,
                        "Type": "transfer",
                        "Id": "abc123",
                    }
                }
            ]
        }
    }
}

ERROR_RESPONSE = {"errors": [{"message": "Field 'Bogus' doesn't exist on type 'Transfer_Set'"}]}


def test_is_configured_true_when_token_set():
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_token():
    settings = Settings(bitquery_access_token=None)
    adapter = BitqueryAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transfer_into_whale_event():
    respx.post(BITQUERY_GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=TRANSFERS_RESPONSE)
    )
    settings = Settings(bitquery_access_token="test-token", bitquery_min_value_usd=500_000)
    adapter = BitqueryAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "bitquery"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "WETH"
    assert event.event_type == "transfer"
    assert event.amount == 12.5
    assert event.amount_usd == 875000.0
    assert event.wallet_address == "0x2222222222222222222222222222222222222222"
    assert event.dedup_key == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_bearer_auth_header():
    route = respx.post(BITQUERY_GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=TRANSFERS_RESPONSE)
    )
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_graphql_error():
    respx.post(BITQUERY_GRAPHQL_URL).mock(return_value=httpx.Response(200, json=ERROR_RESPONSE))
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)

    with pytest.raises(RuntimeError, match="Bogus"):
        await adapter.fetch()
