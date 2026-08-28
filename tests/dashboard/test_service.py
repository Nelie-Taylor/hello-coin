from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from hello_coin.dashboard.service import DashboardService
from hello_coin.ingestion.models import WhaleEvent
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


def _whale_event() -> WhaleEvent:
    return WhaleEvent(
        source="binance",
        timestamp=NOW,
        chain_or_exchange="binance",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.0,
        amount_usd=100_000.0,
        wallet_address=None,
        dedup_key="latest",
        raw={},
    )


def _source(**overrides: object) -> SimpleNamespace:
    values = {
        "name": "binance",
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
        DashboardService(whale_storage, technical_storage, timeframe="1h", lookback_hours=24),
        whale_storage,
        technical_storage,
    )


def test_load_snapshot_includes_scores_recent_events_and_live_source():
    service, whale_storage, technical_storage = _service()
    whale_storage.insert_events([_whale_event()])
    technical_storage.insert_snapshot(_technical_snapshot())

    snapshot = service.load_snapshot("BTCUSDT", [_source()], now=NOW)

    assert snapshot.bias.label == "BULLISH BIAS"
    assert snapshot.whale_events[0]["dedup_key"] == "latest"
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


def test_load_snapshot_keeps_missing_score_as_insufficient_data():
    service, _, technical_storage = _service()
    technical_storage.insert_snapshot(_technical_snapshot())

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert snapshot.bias.label == "INSUFFICIENT DATA"
