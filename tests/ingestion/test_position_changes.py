from datetime import UTC, datetime

from hello_coin.ingestion.models import PositionChange, WhaleEvent
from hello_coin.ingestion.position_changes import PositionChangeTracker


def _position(wallet: str, symbol: str) -> WhaleEvent:
    return WhaleEvent(
        source="hyperdash",
        timestamp=datetime(2026, 8, 29, tzinfo=UTC),
        chain_or_exchange="hyperliquid",
        symbol=symbol,
        event_type="position",
        side="buy",
        amount=2.0,
        amount_usd=125_000.0,
        wallet_address=wallet,
        dedup_key=f"position:{wallet}:{symbol}",
    )


def test_first_refresh_establishes_baseline_without_changes():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")

    assert tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")}) == []


def test_second_refresh_new_position_emits_open_change():
    tracker = PositionChangeTracker()
    tracker.record({}, set())
    event = _position("0xabc", "BTC")

    assert tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")}) == [
        PositionChange("open", event)
    ]


def test_confirmed_absence_of_prior_position_emits_close_change():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")
    tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")})

    assert tracker.record({}, {("0xabc", "BTC")}) == [PositionChange("close", event)]


def test_unconfirmed_absence_keeps_position_without_close_change():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")
    tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")})

    assert tracker.record({}, set()) == []
    assert tracker.record({}, {("0xabc", "BTC")}) == [PositionChange("close", event)]
