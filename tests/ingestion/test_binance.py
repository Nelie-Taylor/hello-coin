import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.binance import BINANCE_TOP_LS_RATIO_URL, BinanceAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = [
    {
        "symbol": "BTCUSDT",
        "longAccount": "0.6647",
        "longShortRatio": "1.9823",
        "shortAccount": "0.3353",
        "timestamp": 1787372700000,
    }
]


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BinanceAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BinanceAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_ratio_into_whale_metric():
    respx.get(BINANCE_TOP_LS_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BinanceAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "binance"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "top_trader_long_short_ratio"
    assert metric.value == 1.9823
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    respx.get(BINANCE_TOP_LS_RATIO_URL).mock(return_value=httpx.Response(200, json=[]))
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BinanceAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
