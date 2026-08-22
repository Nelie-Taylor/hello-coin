from datetime import UTC, datetime

from hello_coin.technical.models import Candle, IndicatorSnapshot


def test_candle_holds_fields():
    candle = Candle(
        open_time=datetime(2026, 8, 22, tzinfo=UTC),
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=12.5,
    )

    assert candle.close == 104.0
    assert candle.volume == 12.5


def test_indicator_snapshot_allows_none_fields_before_enough_history():
    snapshot = IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        close_price=104.0,
        rsi=None,
        macd_line=None,
        macd_signal=None,
        macd_histogram=None,
        bb_upper=None,
        bb_middle=None,
        bb_lower=None,
        ema=None,
        atr=None,
        raw={"candle_count": 5},
    )

    assert snapshot.rsi is None
    assert snapshot.raw == {"candle_count": 5}
