import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.models import Decision
from hello_coin.decision.scheduler import poll_once, run_symbol_loop
from hello_coin.decision.storage import DecisionStorage


def _decision() -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        whale_score=0.49,
        technical_score=0.475,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Aligned signals.",
        raw={},
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_decision_and_returns_count():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(return_value=_decision()),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 1
    assert storage.count_decisions() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_failure():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 0
    assert storage.count_decisions() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = DecisionStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_decision(**kwargs):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _decision()

    with patch("hello_coin.decision.scheduler.compute_decision", new=_fake_compute_decision):
        await run_symbol_loop(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
            stop_event=stop_event,
            poll_interval_seconds=0,
        )

    assert call_count == 1
