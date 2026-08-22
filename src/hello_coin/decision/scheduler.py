import asyncio
import logging
from typing import Any

from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 3600  # 1 hour — matches the technical layer's 1h candle default


async def poll_once(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    liquidation_proximity_pct: float = 0.10,
) -> int:
    try:
        decision = await compute_decision(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
            liquidation_proximity_pct=liquidation_proximity_pct,
        )
    except Exception:
        logger.exception("%s: decision failed", symbol)
        return 0
    return storage.insert_decision(decision)


async def run_symbol_loop(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
    liquidation_proximity_pct: float = 0.10,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
            storage=storage,
            liquidation_proximity_pct=liquidation_proximity_pct,
        )
        logger.info("%s: inserted %d new decision(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str],
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    liquidation_proximity_pct: float = 0.10,
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(
                symbol=symbol,
                timeframe=timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=anthropic_client,
                model=model,
                whale_lookback_hours=whale_lookback_hours,
                storage=storage,
                stop_event=stop_event,
                poll_interval_seconds=poll_interval_seconds,
                liquidation_proximity_pct=liquidation_proximity_pct,
            )
            for symbol in symbols
        )
    )
