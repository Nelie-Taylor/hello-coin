from datetime import UTC, datetime

import pytest

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.score import compute_liquidation_score, nearest_clusters

TIMESTAMP = datetime(2026, 8, 22, tzinfo=UTC)

BUCKETS = [
    LiquidationBucket(price=95.0, notional_usd=1_000_000.0),  # long, distance_pct=0.05
    LiquidationBucket(price=90.0, notional_usd=500_000.0),  # long, distance_pct=0.10 (boundary)
    LiquidationBucket(price=105.0, notional_usd=2_000_000.0),  # short, distance_pct=0.05
    LiquidationBucket(price=120.0, notional_usd=800_000.0),  # short, distance_pct=0.20
]


def _snapshot(buckets: list[LiquidationBucket]) -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT", timestamp=TIMESTAMP, current_price=100.0, buckets=buckets
    )


def test_compute_liquidation_score_weighs_nearby_clusters_by_inverse_distance():
    # Reference calculation (current_price=100, proximity_pct=0.10 default):
    # long @95:  distance=0.05, weight=1,000,000/0.05=20,000,000
    # long @90:  distance=0.10 (boundary, included), weight=500,000/0.10=5,000,000
    # short @105: distance=0.05, weight=2,000,000/0.05=40,000,000
    # short @120: distance=0.20 > 0.10, excluded
    # weighted_long=25,000,000, weighted_short=40,000,000, total=65,000,000
    # score=(40,000,000-25,000,000)/65,000,000=0.23076923076923078
    result = compute_liquidation_score(_snapshot(BUCKETS))
    assert result == pytest.approx(0.23076923076923078)


def test_compute_liquidation_score_excludes_bucket_at_current_price():
    buckets = [LiquidationBucket(price=100.0, notional_usd=999_999.0)]
    assert compute_liquidation_score(_snapshot(buckets)) is None


def test_compute_liquidation_score_is_none_when_nothing_in_proximity():
    buckets = [LiquidationBucket(price=150.0, notional_usd=1_000_000.0)]
    assert compute_liquidation_score(_snapshot(buckets)) is None


def test_compute_liquidation_score_respects_custom_proximity_pct():
    # With proximity_pct=0.25 the @120 short cluster (distance 0.20) is now included:
    # weighted_short += 800,000/0.20=4,000,000 -> weighted_short=44,000,000
    # weighted_long stays 25,000,000, total=69,000,000
    # score=(44,000,000-25,000,000)/69,000,000=0.2753623188405797
    result = compute_liquidation_score(_snapshot(BUCKETS), proximity_pct=0.25)
    assert result == pytest.approx(0.2753623188405797)


def test_nearest_clusters_returns_top_n_by_notional_per_side():
    result = nearest_clusters(_snapshot(BUCKETS), n=2)

    assert result["long_below"] == [(95.0, 1_000_000.0), (90.0, 500_000.0)]
    assert result["short_above"] == [(105.0, 2_000_000.0), (120.0, 800_000.0)]


def test_nearest_clusters_respects_n():
    result = nearest_clusters(_snapshot(BUCKETS), n=1)

    assert result["long_below"] == [(95.0, 1_000_000.0)]
    assert result["short_above"] == [(105.0, 2_000_000.0)]


def test_nearest_clusters_empty_side_returns_empty_list():
    buckets = [LiquidationBucket(price=105.0, notional_usd=2_000_000.0)]
    result = nearest_clusters(_snapshot(buckets))

    assert result["long_below"] == []
    assert result["short_above"] == [(105.0, 2_000_000.0)]
