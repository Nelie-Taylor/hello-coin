from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SourceState = Literal["LIVE", "STALE", "ERROR", "NOT CONFIGURED"]


@dataclass(frozen=True)
class MarketBias:
    whale_score: float | None
    technical_score: float | None
    score: float | None
    label: str


@dataclass(frozen=True)
class SourceStatus:
    name: str
    state: SourceState
    last_success_at: datetime | None
    detail: str


@dataclass(frozen=True)
class DashboardSnapshot:
    symbol: str
    technical: dict[str, Any] | None
    whale_events: tuple[dict[str, Any], ...]
    bias: MarketBias
    source_statuses: tuple[SourceStatus, ...]
    refreshed_at: datetime


def compute_market_bias(whale_score: float | None, technical_score: float | None) -> MarketBias:
    if whale_score is None or technical_score is None:
        return MarketBias(
            whale_score=whale_score,
            technical_score=technical_score,
            score=None,
            label="INSUFFICIENT DATA",
        )
    score = 0.70 * whale_score + 0.30 * technical_score
    if score >= 0.25:
        label = "BULLISH BIAS"
    elif score <= -0.25:
        label = "BEARISH BIAS"
    else:
        label = "WAIT"
    return MarketBias(
        whale_score=whale_score,
        technical_score=technical_score,
        score=score,
        label=label,
    )
