from datetime import UTC, datetime

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.storage import LiquidationStorage


def _snapshot(timestamp: datetime) -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=timestamp,
        current_price=61234.5,
        buckets=[
            LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
            LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
        ],
    )


def test_insert_snapshot_returns_count_and_dedupes():
    storage = LiquidationStorage(":memory:")
    first = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timestamp
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


def test_latest_snapshot_returns_most_recent_reconstructed_snapshot():
    storage = LiquidationStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))

    latest = storage.latest_snapshot("BTCUSDT")

    assert latest is not None
    assert latest.timestamp == datetime(2026, 8, 22, 1, tzinfo=UTC)
    assert latest.current_price == 61234.5
    assert latest.buckets == [
        LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
        LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
    ]


def test_latest_snapshot_returns_none_when_no_rows():
    storage = LiquidationStorage(":memory:")

    assert storage.latest_snapshot("ETHUSDT") is None
