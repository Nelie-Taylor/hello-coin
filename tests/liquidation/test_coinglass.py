import httpx
import pytest
import respx

from hello_coin.ingestion.config import Settings
from hello_coin.liquidation.coinglass import COINGLASS_HEATMAP_URL, fetch_heatmap, is_configured

HEATMAP_RESPONSE = {
    "code": "0",
    "data": {
        "current_price": 61234.5,
        "buckets": [
            {"price": 60000.0, "leverage_value_usd": 1_500_000.0},
            {"price": 63000.0, "leverage_value_usd": 2_000_000.0},
        ],
    },
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(coinglass_api_key="test-key")
    assert is_configured(settings) is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(coinglass_api_key=None)
    assert is_configured(settings) is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_heatmap_sends_api_key_header_and_symbol_param():
    route = respx.get(COINGLASS_HEATMAP_URL).mock(
        return_value=httpx.Response(200, json=HEATMAP_RESPONSE)
    )

    payload = await fetch_heatmap("BTCUSDT", "test-key")

    assert payload == HEATMAP_RESPONSE
    request = route.calls[0].request
    assert request.headers["CG-API-KEY"] == "test-key"
    assert request.url.params["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_heatmap_raises_on_http_error():
    respx.get(COINGLASS_HEATMAP_URL).mock(return_value=httpx.Response(401, json={"code": "401"}))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_heatmap("BTCUSDT", "bad-key")
