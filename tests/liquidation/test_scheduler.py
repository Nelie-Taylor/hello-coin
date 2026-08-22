import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.scheduler import poll_once, run_symbol_loop
from hello_coin.liquidation.storage import LiquidationStorage


def _snapshot() -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=61234.5,
        buckets=[LiquidationBucket(price=60000.0, notional_usd=1_500_000.0)],
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_snapshot_and_returns_count():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(return_value=_snapshot()),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 1
    assert storage.count_snapshots() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_when_snapshot_is_none():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(return_value=None),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_fetch_failure():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = LiquidationStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_snapshot(symbol, api_key):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _snapshot()

    with patch("hello_coin.liquidation.scheduler.compute_snapshot", new=_fake_compute_snapshot):
        await run_symbol_loop("BTCUSDT", "test-key", storage, stop_event, poll_interval_seconds=0)

    assert call_count == 1
