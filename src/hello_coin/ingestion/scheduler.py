import asyncio
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.storage import WhaleStorage

logger = logging.getLogger(__name__)


async def poll_once(adapter: Adapter, storage: WhaleStorage) -> int:
    result = await adapter.safe_fetch()
    if not result:
        return 0
    if isinstance(result[0], WhaleEvent):
        return storage.insert_events(result)
    return storage.insert_metrics(result)


async def run_adapter_loop(
    adapter: Adapter, storage: WhaleStorage, stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(adapter, storage)
        logger.info("%s: inserted %d new row(s)", adapter.name, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=adapter.poll_interval_seconds)
        except asyncio.TimeoutError:
            pass


async def run_forever(adapters: list[Adapter], storage: WhaleStorage) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(run_adapter_loop(adapter, storage, stop_event) for adapter in adapters)
    )
