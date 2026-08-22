from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LiquidationBucket:
    """One price level in a liquidation heatmap and the estimated leveraged
    value that liquidates at that price."""

    price: float
    notional_usd: float


@dataclass(frozen=True)
class LiquidationSnapshot:
    """A point-in-time liquidation heatmap for one symbol. Buckets don't
    carry a long/short side field — a bucket below `current_price` is a
    long-liquidation cluster (longs get force-sold as price falls), one
    above is a short-liquidation cluster (shorts get force-bought as price
    rises); side is derived at scoring time, not stored."""

    symbol: str
    timestamp: datetime
    current_price: float
    buckets: list[LiquidationBucket]
