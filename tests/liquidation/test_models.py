from datetime import UTC, datetime

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def test_liquidation_snapshot_holds_fields():
    snapshot = LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=61234.5,
        buckets=[
            LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
            LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
        ],
    )

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.current_price == 61234.5
    assert len(snapshot.buckets) == 2
    assert snapshot.buckets[0].price == 60000.0
    assert snapshot.buckets[0].notional_usd == 1_500_000.0


def test_liquidation_buckets_compare_by_value():
    assert LiquidationBucket(price=100.0, notional_usd=5.0) == LiquidationBucket(
        price=100.0, notional_usd=5.0
    )
