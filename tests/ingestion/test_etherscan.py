import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.etherscan import ETHERSCAN_V2_API_URL, EtherscanAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

SUCCESS_RESPONSE = {
    "status": "1",
    "message": "OK",
    "result": [
        {
            "blockNumber": "23467053",
            "timeStamp": "1759129619",
            "hash": "0xf9db905d77704596d3600816bc70201586cfeec13bcf576320e2f38d6ca851a",
            "from": "0x2449ecef5012f0a0e153b278ef4fcc9625bc4c78",
            "to": ADDRESS,
            "value": "2500000000000000000",
            "isError": "0",
        },
        {
            "blockNumber": "23467054",
            "timeStamp": "1759129700",
            "hash": "0xdeadbeef00000000000000000000000000000000000000000000000000000",
            "from": "0x1111111111111111111111111111111111111111",
            "to": ADDRESS,
            "value": "1000000000000000000",
            "isError": "1",
        },
    ],
}

NO_TX_RESPONSE = {"status": "0", "message": "No transactions found", "result": []}

ERROR_RESPONSE = {"status": "0", "message": "NOTOK", "result": "Missing/Invalid API Key"}


def _settings(**overrides):
    defaults = {"etherscan_api_key": "test-key", "etherscan_watch_addresses": [ADDRESS]}
    defaults.update(overrides)
    return Settings(**defaults)


def test_is_configured_false_when_no_api_key():
    settings = _settings(etherscan_api_key=None)
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = _settings(etherscan_watch_addresses=[])
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is False


def test_is_configured_true_when_both_set():
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_successful_tx_and_skips_failed_one():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=SUCCESS_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "etherscan_ethereum"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "ETH"
    assert event.event_type == "transfer"
    assert event.side is None
    assert event.amount == 2.5
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xf9db905d77704596d3600816bc70201586cfeec13bcf576320e2f38d6ca851a"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_uses_correct_chain_id_and_symbol_for_bsc():
    route = respx.get(ETHERSCAN_V2_API_URL).mock(
        return_value=httpx.Response(200, json=SUCCESS_RESPONSE)
    )
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="bsc")

    events = await adapter.fetch()

    assert route.calls[0].request.url.params["chainid"] == "56"
    assert events[0].source == "etherscan_bsc"
    assert events[0].chain_or_exchange == "bsc"
    assert events[0].symbol == "BNB"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_transactions_found():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=NO_TX_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    events = await adapter.fetch()

    assert events == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_real_api_error():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=ERROR_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    with pytest.raises(RuntimeError, match="Missing/Invalid API Key"):
        await adapter.fetch()
