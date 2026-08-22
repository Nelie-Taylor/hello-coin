import asyncio
from datetime import UTC, datetime

import pytest

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.scheduler import poll_once, run_adapter_loop
from hello_coin.ingestion.storage import WhaleStorage


def _event(dedup_key: str) -> WhaleEvent:
    return WhaleEvent(
        source="fake",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        chain_or_exchange="fake",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.0,
        amount_usd=1.0,
        wallet_address="0xabc",
        dedup_key=dedup_key,
        raw={},
    )


class _FixedResultAdapter(Adapter):
    name = "fake"
    poll_interval_seconds = 0

    def __init__(self, result):
        super().__init__()
        self._result = result

    async def fetch(self):
        return self._result


@pytest.mark.asyncio
async def test_poll_once_inserts_events_and_returns_count():
    storage = WhaleStorage(":memory:")
    adapter = _FixedResultAdapter([_event("a"), _event("b")])

    inserted = await poll_once(adapter, storage)

    assert inserted == 2
    assert storage.count_events() == 2


@pytest.mark.asyncio
async def test_poll_once_returns_zero_for_empty_result():
    storage = WhaleStorage(":memory:")
    adapter = _FixedResultAdapter([])

    inserted = await poll_once(adapter, storage)

    assert inserted == 0


@pytest.mark.asyncio
async def test_run_adapter_loop_stops_when_event_set_during_fetch():
    storage = WhaleStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    class _OneShotAdapter(Adapter):
        name = "one_shot"
        poll_interval_seconds = 0

        async def fetch(self):
            nonlocal call_count
            call_count += 1
            stop_event.set()
            return []

    await run_adapter_loop(_OneShotAdapter(), storage, stop_event)

    assert call_count == 1
