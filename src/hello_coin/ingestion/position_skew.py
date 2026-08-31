"""Pure, framework-free LONG/SHORT dominance tracking for whale positions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SkewZone = Literal["neutral", "long_dominant", "short_dominant"]

DOMINANT_THRESHOLD = 0.75
EXIT_THRESHOLD = 0.70
SNAPSHOT_INTERVAL_SECONDS = 300


def compute_skew(long_usd: float, short_usd: float) -> tuple[float, float]:
    total = long_usd + short_usd
    if total <= 0:
        return 0.0, 0.0
    return long_usd / total, short_usd / total


def next_zone(current: SkewZone, long_pct: float, short_pct: float) -> SkewZone:
    if current == "neutral":
        if long_pct > DOMINANT_THRESHOLD:
            return "long_dominant"
        if short_pct > DOMINANT_THRESHOLD:
            return "short_dominant"
        return "neutral"
    if current == "long_dominant":
        return "neutral" if long_pct < EXIT_THRESHOLD else "long_dominant"
    return "neutral" if short_pct < EXIT_THRESHOLD else "short_dominant"


@dataclass(frozen=True)
class SkewAlert:
    coin: str
    zone: SkewZone
    direction: Literal["enter", "exit"]
    long_usd: float
    short_usd: float
    long_pct: float
    short_pct: float


@dataclass(frozen=True)
class SkewSnapshot:
    coin: str
    timestamp: datetime
    long_usd: float
    short_usd: float
    long_pct: float
    short_pct: float
    price: float | None = None


class SkewTracker:
    """Per-coin LONG/SHORT dominance state, with hysteresis between 70% and 75%."""

    def __init__(self) -> None:
        self._zones: dict[str, SkewZone] = {}

    def update(self, coin: str, long_usd: float, short_usd: float) -> SkewAlert | None:
        long_pct, short_pct = compute_skew(long_usd, short_usd)
        current = self._zones.get(coin, "neutral")
        new_zone = next_zone(current, long_pct, short_pct)
        alert: SkewAlert | None = None
        if new_zone != current:
            if new_zone == "neutral":
                alert = SkewAlert(coin, current, "exit", long_usd, short_usd, long_pct, short_pct)
            else:
                alert = SkewAlert(coin, new_zone, "enter", long_usd, short_usd, long_pct, short_pct)
        self._zones[coin] = new_zone
        return alert
