from datetime import UTC, datetime

from hello_coin.technical.models import IndicatorSnapshot
from hello_coin.technical.storage import TechnicalStorage


def _snapshot(timestamp: datetime) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=timestamp,
        close_price=100.0,
        rsi=55.0,
        macd_line=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        ema=99.0,
        atr=2.0,
        raw={"candle_count": 100},
    )


def test_insert_snapshot_returns_count_and_dedupes():
    storage = TechnicalStorage(":memory:")
    first = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timeframe/timestamp
    third = _snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC))

    inserted_first = storage.insert_snapshot(first)
    inserted_second = storage.insert_snapshot(second)
    inserted_third = storage.insert_snapshot(third)

    assert inserted_first == 1
    assert inserted_second == 0
    assert inserted_third == 1
    assert storage.count_snapshots() == 2
    assert storage.count_snapshots(symbol="BTCUSDT") == 2
    assert storage.count_snapshots(symbol="ETHUSDT") == 0
