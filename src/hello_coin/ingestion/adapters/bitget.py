from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BITGET_ACCOUNT_LONG_SHORT_URL = "https://api.bitget.com/api/v2/mix/market/account-long-short"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["ts"])
    return WhaleMetric(
        source="bitget",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="long_short_account_ratio",
        value=float(row["longShortAccountRatio"]),
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BitgetAdapter(Adapter):
    """Polls Bitget's public account long/short ratio endpoint for USDT
    futures. No API key needed. The endpoint ignores `limit`, so this
    explicitly picks the max-timestamp row rather than assuming order.
    """

    name = "bitget"
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
                    BITGET_ACCOUNT_LONG_SHORT_URL,
                    params={"symbol": symbol, "productType": "USDT-FUTURES", "period": "5m"},
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                if not rows:
                    continue
                latest = max(rows, key=lambda row: int(row["ts"]))
                metrics.append(_parse_ratio(symbol, latest))
        return metrics
