from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IndicatorSnapshot:
    """A point-in-time snapshot of every computed indicator for one symbol.

    Each indicator field is `float | None` — `None` means there wasn't yet
    enough candle history to compute it, not a fabricated value.
    """

    symbol: str
    timeframe: str
    timestamp: datetime
    close_price: float
    rsi: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    ema: float | None
    atr: float | None
    raw: dict[str, Any] = field(default_factory=dict)
