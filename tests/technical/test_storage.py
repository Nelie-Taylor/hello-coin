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


def test_latest_snapshot_returns_most_recent_row_for_symbol_and_timeframe():
    storage = TechnicalStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))

    latest = storage.latest_snapshot("BTCUSDT", "1h")

    assert latest is not None
    assert latest["timestamp"] == "2026-08-22T01:00:00+00:00"
    assert latest["rsi"] == 55.0


def test_latest_snapshot_returns_none_when_no_rows():
    storage = TechnicalStorage(":memory:")

    assert storage.latest_snapshot("ETHUSDT", "1h") is None


def test_recent_snapshots_uses_an_index_instead_of_scanning_the_table():
    storage = TechnicalStorage(":memory:")

    plan = storage._conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT * FROM technical_snapshots WHERE symbol = 'BTCUSDT' AND timeframe = '1h' "
        "AND timestamp >= '2026-01-01'"
    ).fetchall()

    assert any("USING INDEX" in str(step) for step in plan)


def test_recent_snapshots_filters_by_symbol_timeframe_and_since_ordered_ascending():
    storage = TechnicalStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))
    storage.insert_snapshot(
        IndicatorSnapshot(
            symbol="BTCUSDT",
            timeframe="4h",
            timestamp=datetime(2026, 8, 22, 1, tzinfo=UTC),
            close_price=200.0,
            rsi=None,
            macd_line=None,
            macd_signal=None,
            macd_histogram=None,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            ema=None,
            atr=None,
        )
    )

    rows = storage.recent_snapshots("BTCUSDT", "1h", since=datetime(2026, 8, 21, tzinfo=UTC))

    assert [row["timestamp"] for row in rows] == [
        "2026-08-22T00:00:00+00:00",
        "2026-08-22T01:00:00+00:00",
    ]
