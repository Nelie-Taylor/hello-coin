import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.okx import (
    OKX_LONG_SHORT_RATIO_URL,
    OkxAdapter,
    to_okx_inst_id,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "code": "0",
    "data": [
        ["1787372700000", "1.2740831113213654"],
        ["1787372400000", "1.2745161531372207"],
    ],
    "msg": "",
}


def test_to_okx_inst_id_converts_usdt_pair():
    assert to_okx_inst_id("BTCUSDT") == "BTC-USDT-SWAP"


def test_to_okx_inst_id_rejects_non_usdt_pair():
    with pytest.raises(ValueError, match="BTCBUSD"):
        to_okx_inst_id("BTCBUSD")


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = OkxAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = OkxAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_latest_ratio_into_whale_metric():
    respx.get(OKX_LONG_SHORT_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = OkxAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "okx"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    assert metric.value == 1.2740831113213654
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    respx.get(OKX_LONG_SHORT_RATIO_URL).mock(
        return_value=httpx.Response(200, json={"code": "0", "data": [], "msg": ""})
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = OkxAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
