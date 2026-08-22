from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.technical.models import Candle
from hello_coin.technical.service import DEFAULT_CANDLE_LIMIT, compute_snapshot


def _candle(i: int) -> Candle:
    price = 100.0 + i
    return Candle(
        open_time=datetime.fromtimestamp(1_700_000_000 + i * 3600, tz=UTC),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=10.0,
    )


@pytest.mark.asyncio
async def test_compute_snapshot_combines_fetch_and_indicators():
    # MACD(fast=12, slow=26, signal=9) needs at least slow + signal - 1 = 34 candles
    # before its macd-line series is long enough to produce a non-None signal —
    # fewer candles than that would leave macd_line/signal/histogram all None even
    # though RSI/Bollinger/EMA/ATR (which need at most 20) would already be populated.
    candles = [_candle(i) for i in range(40)]
    with patch(
        "hello_coin.technical.service.fetch_klines", new=AsyncMock(return_value=candles)
    ) as mock_fetch:
        snapshot = await compute_snapshot("BTCUSDT", "1h")

    mock_fetch.assert_awaited_once_with("BTCUSDT", "1h", DEFAULT_CANDLE_LIMIT)
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.timeframe == "1h"
    assert snapshot.close_price == candles[-1].close
    assert snapshot.timestamp == candles[-1].open_time
    # 40 candles is enough history for every indicator to be non-None.
    assert snapshot.rsi is not None
    assert snapshot.macd_line is not None
    assert snapshot.bb_upper is not None
    assert snapshot.ema is not None
    assert snapshot.atr is not None


@pytest.mark.asyncio
async def test_compute_snapshot_leaves_indicators_none_with_short_history():
    candles = [_candle(i) for i in range(5)]
    with patch("hello_coin.technical.service.fetch_klines", new=AsyncMock(return_value=candles)):
        snapshot = await compute_snapshot("BTCUSDT", "1h")

    assert snapshot.rsi is None
    assert snapshot.macd_line is None
    assert snapshot.bb_upper is None
