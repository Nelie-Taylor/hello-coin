from datetime import UTC, datetime

import pytest

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
from hello_coin.ingestion.position_skew import SkewSnapshot
from hello_coin.ingestion.storage import WhaleStorage


def _event(dedup_key: str, hour: int = 0) -> WhaleEvent:
    return WhaleEvent(
        source="hyperliquid",
        timestamp=datetime(2026, 8, 22, hour, tzinfo=UTC),
        chain_or_exchange="hyperliquid",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.0,
        amount_usd=60000.0,
        wallet_address="0xabc",
        dedup_key=dedup_key,
        raw={},
    )


def test_insert_events_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")

    inserted_first = storage.insert_events([_event("a"), _event("b")])
    inserted_second = storage.insert_events([_event("a"), _event("c")])

    assert inserted_first == 2
    assert inserted_second == 1
    assert storage.count_events() == 3
    assert storage.count_events(source="hyperliquid") == 3
    assert storage.count_events(source="other") == 0


def test_insert_metrics_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")
    metric = WhaleMetric(
        source="binance",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        symbol="BTCUSDT",
        metric_name="oi",
        value=1.0,
        dedup_key="m1",
        raw={},
    )

    inserted_first = storage.insert_metrics([metric])
    inserted_second = storage.insert_metrics([metric])

    assert inserted_first == 1
    assert inserted_second == 0


def test_recent_events_uses_an_index_instead_of_scanning_the_table():
    storage = WhaleStorage(":memory:")

    plan = storage._conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT * FROM whale_events WHERE symbol = 'BTC' COLLATE NOCASE AND timestamp >= '2026-01-01'"
    ).fetchall()

    assert any("USING INDEX" in str(step) for step in plan)


def test_recent_metrics_uses_an_index_instead_of_scanning_the_table():
    storage = WhaleStorage(":memory:")

    plan = storage._conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT * FROM whale_metrics WHERE symbol = 'BTCUSDT' COLLATE NOCASE AND timestamp >= '2026-01-01'"
    ).fetchall()

    assert any("USING INDEX" in str(step) for step in plan)


def test_recent_events_filters_by_symbol_case_insensitive_and_since():
    storage = WhaleStorage(":memory:")
    old_event = _event("a")  # symbol="BTC", timestamp=2026-08-22 (see _event() above)
    storage.insert_events([old_event])

    matching = storage.recent_events("btc", since=datetime(2026, 8, 21, tzinfo=UTC))
    too_late = storage.recent_events("btc", since=datetime(2026, 8, 23, tzinfo=UTC))
    wrong_symbol = storage.recent_events("eth", since=datetime(2026, 8, 21, tzinfo=UTC))

    assert len(matching) == 1
    assert matching[0]["side"] == "buy"
    assert matching[0]["amount_usd"] == 60000.0
    assert too_late == []
    assert wrong_symbol == []


def test_latest_events_returns_matching_rows_newest_first_with_limit():
    storage = WhaleStorage(":memory:")
    storage.insert_events([_event("old", hour=0), _event("new", hour=1)])

    events = storage.latest_events("btc", limit=1)

    assert [event["dedup_key"] for event in events] == ["new"]


def test_latest_events_rejects_non_positive_limit():
    storage = WhaleStorage(":memory:")

    with pytest.raises(ValueError, match="limit must be positive"):
        storage.latest_events("BTC", limit=0)


def test_latest_events_accepts_multiple_symbols_merged_newest_first():
    storage = WhaleStorage(":memory:")
    btc_event = _event("btc-old", hour=0)
    link_event = WhaleEvent(
        source="hyperdash",
        timestamp=datetime(2026, 8, 22, 1, tzinfo=UTC),
        chain_or_exchange="hyperliquid",
        symbol="LINK",
        event_type="position",
        side="sell",
        amount=2.0,
        amount_usd=125_000.0,
        wallet_address="0xdef",
        dedup_key="link-new",
        raw={},
    )
    storage.insert_events([btc_event, link_event])

    events = storage.latest_events(["btc", "link"], limit=10)

    assert [event["dedup_key"] for event in events] == ["link-new", "btc-old"]


def test_latest_events_with_multiple_symbols_excludes_others():
    storage = WhaleStorage(":memory:")
    storage.insert_events([_event("btc-only")])

    events = storage.latest_events(["link", "sol"], limit=10)

    assert events == []


def test_recent_metrics_filters_by_symbol_case_insensitive_and_since():
    storage = WhaleStorage(":memory:")
    metric = WhaleMetric(
        source="binance",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        symbol="BTCUSDT",
        metric_name="top_trader_long_short_ratio",
        value=1.8,
        dedup_key="m1",
        raw={},
    )
    storage.insert_metrics([metric])

    matching = storage.recent_metrics("btcusdt", since=datetime(2026, 8, 21, tzinfo=UTC))
    wrong_symbol = storage.recent_metrics("btc", since=datetime(2026, 8, 21, tzinfo=UTC))

    assert len(matching) == 1
    assert matching[0]["metric_name"] == "top_trader_long_short_ratio"
    assert matching[0]["value"] == 1.8
    assert wrong_symbol == []


def _skew_snapshot(coin: str, timestamp: datetime, long_pct: float = 0.8) -> SkewSnapshot:
    return SkewSnapshot(
        coin=coin,
        timestamp=timestamp,
        long_usd=long_pct * 1_000_000,
        short_usd=(1 - long_pct) * 1_000_000,
        long_pct=long_pct,
        short_pct=1 - long_pct,
    )


def test_insert_skew_snapshots_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")
    snapshot = _skew_snapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC))

    inserted_first = storage.insert_skew_snapshots([snapshot])
    inserted_second = storage.insert_skew_snapshots([snapshot])

    assert inserted_first == 1
    assert inserted_second == 0


def test_insert_skew_snapshots_prunes_rows_older_than_30_days_relative_to_batch():
    storage = WhaleStorage(":memory:")
    storage.insert_skew_snapshots([_skew_snapshot("LINK", datetime(2026, 1, 1, tzinfo=UTC))])

    newer = datetime(2026, 8, 31, tzinfo=UTC)
    storage.insert_skew_snapshots([_skew_snapshot("LINK", newer)])

    remaining = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [row["timestamp"] for row in remaining] == [newer.isoformat()]


def test_insert_skew_snapshots_keeps_rows_within_30_days_of_batch():
    storage = WhaleStorage(":memory:")
    within_window = datetime(2026, 8, 5, tzinfo=UTC)  # 26 days before the batch below
    storage.insert_skew_snapshots([_skew_snapshot("LINK", within_window)])

    storage.insert_skew_snapshots([_skew_snapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC))])

    remaining = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert len(remaining) == 2


def test_recent_skew_history_filters_by_coin_case_insensitive_since_ordered_ascending():
    storage = WhaleStorage(":memory:")
    storage.insert_skew_snapshots([
        _skew_snapshot("LINK", datetime(2026, 8, 31, 0, 0, tzinfo=UTC), long_pct=0.6),
        _skew_snapshot("LINK", datetime(2026, 8, 31, 0, 5, tzinfo=UTC), long_pct=0.7),
        _skew_snapshot("SOL", datetime(2026, 8, 31, 0, 5, tzinfo=UTC), long_pct=0.9),
    ])

    rows = storage.recent_skew_history("link", since=datetime(2026, 8, 31, tzinfo=UTC))

    assert [row["long_pct"] for row in rows] == [0.6, 0.7]
