from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SourceState = Literal["LIVE", "STALE", "ERROR", "NOT CONFIGURED"]


@dataclass(frozen=True)
class MarketBias:
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
class CoinPositionTable:
    coin: str
    rows: tuple[dict[str, Any], ...]
    status: SourceStatus
    skew_history: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DashboardSnapshot:
    symbol: str
    technical: dict[str, Any] | None
    bias: MarketBias
    source_statuses: tuple[SourceStatus, ...]
    refreshed_at: datetime
    coin_positions: tuple[CoinPositionTable, ...] = ()


def compute_market_bias(technical_score: float | None) -> MarketBias:
    if technical_score is None:
        return MarketBias(technical_score=None, score=None, label="INSUFFICIENT DATA")
    score = technical_score
    if score >= 0.25:
        label = "BULLISH BIAS"
    elif score <= -0.25:
        label = "BEARISH BIAS"
    else:
        label = "WAIT"
    return MarketBias(technical_score=technical_score, score=score, label=label)
