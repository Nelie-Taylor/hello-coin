import asyncio
import logging

from hello_coin.liquidation.service import compute_snapshot
from hello_coin.liquidation.storage import LiquidationStorage

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 900  # 15 min — heatmaps don't change fast; Coinglass is paid


async def poll_once(symbol: str, api_key: str, storage: LiquidationStorage) -> int:
    try:
        snapshot = await compute_snapshot(symbol, api_key)
    except Exception:
        logger.exception("%s: liquidation snapshot fetch failed", symbol)
        return 0
    if snapshot is None:
        return 0
    return storage.insert_snapshot(snapshot)


async def run_symbol_loop(
    symbol: str,
    api_key: str,
    storage: LiquidationStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(symbol, api_key, storage)
        logger.info("%s: inserted %d new row(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str],
    api_key: str,
    storage: LiquidationStorage,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(symbol, api_key, storage, stop_event, poll_interval_seconds)
            for symbol in symbols
        )
    )
