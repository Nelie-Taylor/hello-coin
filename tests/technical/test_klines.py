import httpx
import pytest
import respx

from hello_coin.technical.klines import BINANCE_KLINES_URL, fetch_klines
from hello_coin.technical.models import Candle

KLINES_RESPONSE = [
    [
        1787367600000,
        "78467.90",
        "78831.80",
        "78344.30",
        "78395.00",
        "6088.611",
        1787371199999,
        "478553147.28660",
        187608,
        "3012.611",
        "236819326.95900",
        "0",
    ],
    [
        1787371200000,
        "78395.00",
        "78815.20",
        "78183.10",
        "78453.30",
        "5979.954",
        1787374799999,
        "469471517.23890",
        197325,
        "2972.938",
        "233391676.12620",
        "0",
    ],
]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_klines_parses_response_into_candles():
    respx.get(BINANCE_KLINES_URL).mock(return_value=httpx.Response(200, json=KLINES_RESPONSE))

    candles = await fetch_klines("BTCUSDT", "1h", 2)

    assert len(candles) == 2
    candle = candles[0]
    assert isinstance(candle, Candle)
    assert candle.open == 78467.90
    assert candle.high == 78831.80
    assert candle.low == 78344.30
    assert candle.close == 78395.00
    assert candle.volume == 6088.611


@pytest.mark.asyncio
@respx.mock
async def test_fetch_klines_sends_symbol_interval_limit_params():
    route = respx.get(BINANCE_KLINES_URL).mock(
        return_value=httpx.Response(200, json=KLINES_RESPONSE)
    )

    await fetch_klines("ETHUSDT", "4h", 50)

    params = route.calls[0].request.url.params
    assert params["symbol"] == "ETHUSDT"
    assert params["interval"] == "4h"
    assert params["limit"] == "50"
