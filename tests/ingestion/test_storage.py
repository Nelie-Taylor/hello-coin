from datetime import UTC, datetime

import pytest

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
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
