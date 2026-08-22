import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bybit import BYBIT_ACCOUNT_RATIO_URL, BybitAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "list": [
            {"symbol": "BTCUSDT", "buyRatio": "0.5395", "sellRatio": "0.4605", "timestamp": "1787372700000"}
        ],
        "nextPageCursor": "lastid=0&lasttime=1787372700",
    },
    "retExtInfo": {},
    "time": 1787372829259,
}


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BybitAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BybitAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_ratio_into_whale_metric():
    respx.get(BYBIT_ACCOUNT_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BybitAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "bybit"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    assert metric.value == pytest.approx(0.5395 / 0.4605)
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    empty_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": [], "nextPageCursor": ""},
        "retExtInfo": {},
        "time": 1787372829259,
    }
    respx.get(BYBIT_ACCOUNT_RATIO_URL).mock(return_value=httpx.Response(200, json=empty_response))
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BybitAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
