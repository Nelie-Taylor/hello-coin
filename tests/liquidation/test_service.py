from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.liquidation.service import compute_snapshot

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


@pytest.mark.asyncio
async def test_compute_snapshot_parses_heatmap_into_buckets():
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap",
        new=AsyncMock(return_value=HEATMAP_RESPONSE),
    ) as mock_fetch:
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    mock_fetch.assert_awaited_once_with("BTCUSDT", "test-key")
    assert snapshot is not None
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.current_price == 61234.5
    assert len(snapshot.buckets) == 2
    assert snapshot.buckets[0].price == 60000.0
    assert snapshot.buckets[0].notional_usd == 1_500_000.0


@pytest.mark.asyncio
async def test_compute_snapshot_returns_none_when_data_missing():
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap",
        new=AsyncMock(return_value={"code": "0"}),
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is None


@pytest.mark.asyncio
async def test_compute_snapshot_skips_buckets_missing_fields():
    response = {
        "code": "0",
        "data": {
            "current_price": 100.0,
            "buckets": [{"price": 95.0}, {"price": 105.0, "leverage_value_usd": 10.0}],
        },
    }
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap", new=AsyncMock(return_value=response)
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is not None
    assert len(snapshot.buckets) == 1
    assert snapshot.buckets[0].price == 105.0


@pytest.mark.asyncio
async def test_compute_snapshot_returns_none_when_all_buckets_unparseable():
    response = {"code": "0", "data": {"current_price": 100.0, "buckets": [{"price": 95.0}]}}
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap", new=AsyncMock(return_value=response)
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is None
