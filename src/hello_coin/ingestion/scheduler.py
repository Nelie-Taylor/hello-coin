import asyncio
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.notifications import NotificationSink
from hello_coin.ingestion.storage import WhaleStorage

logger = logging.getLogger(__name__)


async def poll_once(
    adapter: Adapter,
    storage: WhaleStorage,
    notifier: NotificationSink | None = None,
) -> int:
    result = await adapter.safe_fetch()
    if not result:
        inserted = 0
    elif isinstance(result[0], WhaleEvent):
        inserted = storage.insert_events(result)
    else:
        inserted = storage.insert_metrics(result)

    storage.insert_skew_snapshots(adapter.consume_skew_snapshots())

    if notifier is not None:
        for alert in adapter.consume_skew_alerts():
            try:
                await notifier.notify(alert)
            except Exception:
                logger.exception("failed to deliver whale position notification")
    return inserted


async def run_adapter_loop(
    adapter: Adapter,
    storage: WhaleStorage,
    stop_event: asyncio.Event,
    notifier: NotificationSink | None = None,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(adapter, storage, notifier)
        logger.info("%s: inserted %d new row(s)", adapter.name, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=adapter.poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    adapters: list[Adapter], storage: WhaleStorage, notifier: NotificationSink | None = None
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(run_adapter_loop(adapter, storage, stop_event, notifier) for adapter in adapters)
    )
