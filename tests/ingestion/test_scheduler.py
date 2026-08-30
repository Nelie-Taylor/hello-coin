import asyncio
from datetime import UTC, datetime

import pytest

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.position_skew import SkewAlert
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


class _SkewAlertAdapter(_FixedResultAdapter):
    def __init__(self, result, alerts: list[SkewAlert]) -> None:
        super().__init__(result)
        self._alerts = alerts

    def consume_skew_alerts(self) -> list[SkewAlert]:
        alerts = self._alerts
        self._alerts = []
        return alerts


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


@pytest.mark.asyncio
async def test_poll_once_notifies_changes_after_persisting_events():
    storage = WhaleStorage(":memory:")
    event = _event("new")
    alert = SkewAlert("BTC", "long_dominant", "enter", 800_000.0, 200_000.0, 0.8, 0.2)
    adapter = _SkewAlertAdapter([event], [alert])

    class _Notifier:
        def __init__(self) -> None:
            self.count_when_notified = 0
            self.alerts: list[SkewAlert] = []

        async def notify(self, alert: SkewAlert) -> None:
            self.count_when_notified = storage.count_events()
            self.alerts.append(alert)

    notifier = _Notifier()

    inserted = await poll_once(adapter, storage, notifier)

    assert inserted == 1
    assert notifier.count_when_notified == 1
    assert notifier.alerts == [alert]


@pytest.mark.asyncio
async def test_poll_once_logs_notifier_failure_and_returns_insert_count(caplog):
    storage = WhaleStorage(":memory:")
    event = _event("new")
    alert = SkewAlert("BTC", "long_dominant", "enter", 800_000.0, 200_000.0, 0.8, 0.2)
    adapter = _SkewAlertAdapter([event], [alert])

    class _FailingNotifier:
        async def notify(self, alert: SkewAlert) -> None:
            raise RuntimeError("telegram unavailable")

    inserted = await poll_once(adapter, storage, _FailingNotifier())

    assert inserted == 1
    assert "failed to deliver whale position notification" in caplog.text
