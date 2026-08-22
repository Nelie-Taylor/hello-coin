import pytest

from hello_coin.technical.service import compute_snapshot


@pytest.mark.network
@pytest.mark.asyncio
async def test_compute_snapshot_reaches_real_binance_api():
    snapshot = await compute_snapshot("BTCUSDT", "1h")

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.close_price > 0
    # 100 candles (DEFAULT_CANDLE_LIMIT) is enough history for every indicator.
    assert snapshot.rsi is not None
    assert snapshot.macd_line is not None
    assert snapshot.bb_upper is not None
