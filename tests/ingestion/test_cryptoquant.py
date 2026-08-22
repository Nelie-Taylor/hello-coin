import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.cryptoquant import (
    CRYPTOQUANT_WHALE_RATIO_URL,
    CryptoQuantAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "status": {"code": 200, "message": "success"},
    "result": {
        "window": "day",
        "data": [
            {"date": "2026-08-20", "exchange_whale_ratio": 0.42},
            {"date": "2026-08-21", "exchange_whale_ratio": 0.47},
        ],
    },
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(cryptoquant_api_key=None)
    adapter = CryptoQuantAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_latest_ratio_into_whale_metric():
    respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "cryptoquant"
    assert metric.symbol == "BTC"
    assert metric.metric_name == "exchange_whale_ratio"
    assert metric.value == 0.47
    assert metric.dedup_key == "BTC:2026-08-21"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_bearer_auth_header():
    route = respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_data():
    empty_response = {"status": {"code": 200, "message": "success"}, "result": {"data": []}}
    respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
