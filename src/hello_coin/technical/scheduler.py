import asyncio
import logging

from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

logger = logging.getLogger(__name__)


async def poll_once(symbol: str, timeframe: str, storage: TechnicalStorage) -> int:
    try:
        snapshot = await compute_snapshot(symbol, timeframe)
    except Exception:
        logger.exception("%s: technical snapshot fetch failed", symbol)
        return 0
    return storage.insert_snapshot(snapshot)


async def run_symbol_loop(
    symbol: str,
    timeframe: str,
    storage: TechnicalStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(symbol, timeframe, storage)
        logger.info("%s: inserted %d new row(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str], timeframe: str, storage: TechnicalStorage, poll_interval_seconds: int = 900
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(symbol, timeframe, storage, stop_event, poll_interval_seconds)
            for symbol in symbols
        )
    )
