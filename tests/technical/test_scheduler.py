import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.technical.models import IndicatorSnapshot
from hello_coin.technical.scheduler import poll_once, run_symbol_loop
from hello_coin.technical.storage import TechnicalStorage


def _snapshot() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
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
        raw={},
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_snapshot_and_returns_count():
    storage = TechnicalStorage(":memory:")
    with patch(
        "hello_coin.technical.scheduler.compute_snapshot",
        new=AsyncMock(return_value=_snapshot()),
    ):
        inserted = await poll_once("BTCUSDT", "1h", storage)

    assert inserted == 1
    assert storage.count_snapshots() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_fetch_failure(caplog):
    storage = TechnicalStorage(":memory:")
    with patch(
        "hello_coin.technical.scheduler.compute_snapshot",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once("BTCUSDT", "1h", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = TechnicalStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_snapshot(symbol, timeframe):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _snapshot()

    with patch(
        "hello_coin.technical.scheduler.compute_snapshot", new=_fake_compute_snapshot
    ):
        await run_symbol_loop("BTCUSDT", "1h", storage, stop_event, poll_interval_seconds=0)

    assert call_count == 1
