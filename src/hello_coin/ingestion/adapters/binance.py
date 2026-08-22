from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BINANCE_TOP_LS_RATIO_URL = "https://fapi.binance.com/futures/data/topLongShortPositionRatio"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["timestamp"])
    return WhaleMetric(
        source="binance",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="top_trader_long_short_ratio",
        value=float(row["longShortRatio"]),
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BinanceAdapter(Adapter):
    """Polls Binance Futures' public Top Trader Long/Short Ratio (Positions)
    endpoint — the top 20% of accounts by margin balance, a direct whale
    proxy. No API key needed.
    """

    name = "binance"
    poll_interval_seconds = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.exchange_watch_symbols)

    async def fetch(self) -> list[WhaleMetric]:
        metrics: list[WhaleMetric] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in self._settings.exchange_watch_symbols:
                response = await client.get(
                    BINANCE_TOP_LS_RATIO_URL,
                    params={"symbol": symbol, "period": "5m", "limit": 1},
                )
                response.raise_for_status()
                rows = response.json()
                if not rows:
                    continue
                metrics.append(_parse_ratio(symbol, rows[0]))
        return metrics
