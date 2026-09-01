from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WhaleEvent:
    """A single discrete whale action tied to one wallet (transfer, fill, position)."""

    source: str
    timestamp: datetime
    chain_or_exchange: str
    symbol: str
    event_type: str  # "transfer" | "fill" | "position"
    side: str | None
    amount: float
    amount_usd: float | None
    wallet_address: str | None
    dedup_key: str
    raw: dict[str, Any] = field(default_factory=dict)
