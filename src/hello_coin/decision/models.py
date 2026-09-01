from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Decision:
    """One AI-made trade decision for a symbol at a point in time."""

    symbol: str
    timestamp: datetime
    technical_score: float | None
    liquidation_score: float | None
    weighted_score: float | None
    action: str  # "buy" | "sell" | "hold"
    confidence: float
    reasoning: str
    raw: dict[str, Any] = field(default_factory=dict)
