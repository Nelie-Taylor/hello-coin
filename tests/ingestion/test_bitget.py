import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bitget import (
    BITGET_ACCOUNT_LONG_SHORT_URL,
    BitgetAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "code": "00000",
    "msg": "success",
    "requestTime": 1787372828693,
    "data": [
        {
            "longAccountRatio": "0.5676",
            "shortAccountRatio": "0.4324",
            "longShortAccountRatio": "1.3126",
            "ts": "1787372100000",
        },
        {
            "longAccountRatio": "0.5673",
            "shortAccountRatio": "0.4327",
            "longShortAccountRatio": "1.311",
            "ts": "1787372400000",
        },
    ],
}


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BitgetAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BitgetAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_selects_max_timestamp_row_regardless_of_order():
    respx.get(BITGET_ACCOUNT_LONG_SHORT_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BitgetAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "bitget"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    # RATIO_RESPONSE[1] has the larger "ts" despite being listed second —
    # the adapter must pick it by value, not by list position.
    assert metric.value == 1.311
    assert metric.dedup_key == "BTCUSDT:1787372400000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    empty_response = {"code": "00000", "msg": "success", "requestTime": 1, "data": []}
    respx.get(BITGET_ACCOUNT_LONG_SHORT_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BitgetAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
