from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BYBIT_ACCOUNT_RATIO_URL = "https://api.bybit.com/v5/market/account-ratio"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["timestamp"])
    buy_ratio = float(row["buyRatio"])
    sell_ratio = float(row["sellRatio"])
    value = buy_ratio / sell_ratio if sell_ratio else 0.0
    return WhaleMetric(
        source="bybit",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="long_short_account_ratio",
        value=value,
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BybitAdapter(Adapter):
    """Polls Bybit's public account long/short ratio endpoint for linear
    (USDT-margined) perps. No API key needed.
    """

    name = "bybit"
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
                    BYBIT_ACCOUNT_RATIO_URL,
                    params={"category": "linear", "symbol": symbol, "period": "5min", "limit": 1},
                )
                response.raise_for_status()
                rows = response.json().get("result", {}).get("list", [])
                if not rows:
                    continue
                metrics.append(_parse_ratio(symbol, rows[0]))
        return metrics
