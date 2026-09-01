import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hello_coin.dashboard.service import DashboardService
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.position_skew import SkewSnapshot
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.models import IndicatorSnapshot
from hello_coin.technical.storage import TechnicalStorage

NOW = datetime(2026, 8, 29, 0, 1, tzinfo=UTC)


def _technical_snapshot() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=NOW,
        close_price=100.0,
        rsi=30.0,
        macd_line=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=110.0,
        bb_middle=95.0,
        bb_lower=80.0,
        ema=90.0,
        atr=2.0,
        raw={},
    )


def _source(**overrides: object) -> SimpleNamespace:
    values = {
        "name": "hyperdash",
        "poll_interval_seconds": 60,
        "last_success_at": NOW - timedelta(seconds=30),
        "last_error": None,
        "disabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service() -> tuple[DashboardService, WhaleStorage, TechnicalStorage]:
    whale_storage = WhaleStorage(":memory:")
    technical_storage = TechnicalStorage(":memory:")
    return (
        DashboardService(whale_storage, technical_storage, timeframe="1h"),
        whale_storage,
        technical_storage,
    )


def test_load_snapshot_groups_fresh_hyperdash_positions_per_coin():
    whale_storage = WhaleStorage(":memory:")
    service = DashboardService(
        whale_storage,
        TechnicalStorage(":memory:"),
        timeframe="1h",
        hyperdash_watch_coins=["LINK", "SOL", "SUI", "NEAR", "HYPE"],
    )
    whale_storage.insert_events([
        WhaleEvent(
            source="hyperdash", timestamp=NOW, chain_or_exchange="hyperliquid", symbol="LINK",
            event_type="position", side="buy", amount=2, amount_usd=80_000,
            wallet_address="0x1234567890abcdef", dedup_key="p1",
            raw={"entryPx": "10", "leverage": {"type": "cross", "value": 7}},
        ),
    ])

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert [table.coin for table in snapshot.coin_positions] == ["LINK", "SOL", "SUI", "NEAR", "HYPE"]
    assert snapshot.coin_positions[0].rows[0]["wallet_address"] == "0x1234567890abcdef"
    assert snapshot.coin_positions[0].rows[0]["raw"]["leverage"]["value"] == 7
    assert snapshot.coin_positions[1].rows == ()


def test_load_snapshot_orders_coin_positions_by_usd_value_descending():
    whale_storage = WhaleStorage(":memory:")
    service = DashboardService(
        whale_storage,
        TechnicalStorage(":memory:"),
        timeframe="1h",
        hyperdash_watch_coins=["LINK"],
    )
    whale_storage.insert_events([
        WhaleEvent(
            source="hyperdash", timestamp=NOW, chain_or_exchange="hyperliquid", symbol="LINK",
            event_type="position", side="buy", amount=1, amount_usd=60_000,
            wallet_address="0xsmall", dedup_key="small", raw={},
        ),
        WhaleEvent(
            source="hyperdash", timestamp=NOW, chain_or_exchange="hyperliquid", symbol="LINK",
            event_type="position", side="sell", amount=2, amount_usd=180_000,
            wallet_address="0xlarge", dedup_key="large", raw={},
        ),
        WhaleEvent(
            source="hyperdash", timestamp=NOW, chain_or_exchange="hyperliquid", symbol="LINK",
            event_type="position", side="buy", amount=1.5, amount_usd=90_000,
            wallet_address="0xmedium", dedup_key="medium", raw={},
        ),
    ])

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert [row["amount_usd"] for row in snapshot.coin_positions[0].rows] == [
        180_000,
        90_000,
        60_000,
    ]


def test_load_snapshot_hides_stale_hyperdash_positions():
    whale_storage = WhaleStorage(":memory:")
    service = DashboardService(
        whale_storage, TechnicalStorage(":memory:"), timeframe="1h",
        hyperdash_watch_coins=["LINK"], position_freshness_seconds=120,
    )
    whale_storage.insert_events([
        WhaleEvent(
            source="hyperdash", timestamp=NOW - timedelta(seconds=121), chain_or_exchange="hyperliquid",
            symbol="LINK", event_type="position", side="sell", amount=1, amount_usd=60_000,
            wallet_address="0xabc", dedup_key="stale", raw={},
        )
    ])

    source = SimpleNamespace(
        name="hyperdash", poll_interval_seconds=60,
        disabled=False, last_error=None, last_success_at=NOW,
        coin_statuses={"LINK": {"state": "LIVE", "detail": "0 qualifying wallet(s)", "last_success_at": NOW}},
    )
    snapshot = service.load_snapshot("BTCUSDT", [source], now=NOW)

    assert snapshot.coin_positions[0].rows == ()
    assert snapshot.coin_positions[0].status.state == "STALE"


def test_load_snapshot_includes_technical_bias_and_live_source():
    service, _, technical_storage = _service()
    technical_storage.insert_snapshot(_technical_snapshot())

    snapshot = service.load_snapshot("BTCUSDT", [_source()], now=NOW)

    assert snapshot.bias.label == "BULLISH BIAS"
    assert snapshot.bias.technical_score == pytest.approx(0.5166666666666667)
    assert snapshot.source_statuses[0].state == "LIVE"


def test_load_snapshot_marks_source_with_error():
    service, _, _ = _service()

    snapshot = service.load_snapshot("BTCUSDT", [_source(last_error="offline")], now=NOW)

    assert snapshot.source_statuses[0].state == "ERROR"
    assert snapshot.source_statuses[0].detail == "offline"


def test_load_snapshot_marks_stale_source():
    service, _, _ = _service()

    snapshot = service.load_snapshot(
        "BTCUSDT", [_source(last_success_at=NOW - timedelta(seconds=121))], now=NOW
    )

    assert snapshot.source_statuses[0].state == "STALE"


def test_load_snapshot_reports_insufficient_data_without_technical_snapshot():
    service, _, _ = _service()

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert snapshot.bias.label == "INSUFFICIENT DATA"
    assert snapshot.bias.score is None


def test_close_closes_both_storage_connections():
    service, whale_storage, technical_storage = _service()

    service.close()

    with pytest.raises(sqlite3.ProgrammingError):
        whale_storage.count_events()
    with pytest.raises(sqlite3.ProgrammingError):
        technical_storage.count_snapshots()


def test_load_snapshot_includes_skew_history_per_coin():
    whale_storage = WhaleStorage(":memory:")
    service = DashboardService(
        whale_storage,
        TechnicalStorage(":memory:"),
        timeframe="1h",
        hyperdash_watch_coins=["LINK"],
    )
    whale_storage.insert_skew_snapshots([
        SkewSnapshot("LINK", NOW - timedelta(minutes=5), 800_000.0, 200_000.0, 0.8, 0.2),
        SkewSnapshot("LINK", NOW, 700_000.0, 300_000.0, 0.7, 0.3),
    ])

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert [row["long_pct"] for row in snapshot.coin_positions[0].skew_history] == [0.8, 0.7]
