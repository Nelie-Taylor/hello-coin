from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

CRYPTOQUANT_WHALE_RATIO_URL = (
    "https://api.cryptoquant.com/v1/btc/flow-indicator/exchange-whale-ratio"
)


def _parse_row(row: dict[str, Any]) -> WhaleMetric:
    date_str = row["date"]
    return WhaleMetric(
        source="cryptoquant",
        timestamp=datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC),
        symbol="BTC",
        metric_name="exchange_whale_ratio",
        value=float(row["exchange_whale_ratio"]),
        dedup_key=f"BTC:{date_str}",
        raw=row,
    )


class CryptoQuantAdapter(Adapter):
    """Polls CryptoQuant's Exchange Whale Ratio indicator for BTC on Binance
    — one of the few indicators available on CryptoQuant's free tier. Needs a
    CryptoQuant API key (Bearer auth).
    """

    name = "cryptoquant"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.cryptoquant_api_key)

    async def fetch(self) -> list[WhaleMetric]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                CRYPTOQUANT_WHALE_RATIO_URL,
                params={"exchange": "binance", "window": "day", "limit": 1},
                headers={"Authorization": f"Bearer {self._settings.cryptoquant_api_key}"},
            )
            response.raise_for_status()
            rows = response.json().get("result", {}).get("data", [])
            if not rows:
                return []
            latest = max(rows, key=lambda row: row["date"])
            return [_parse_row(latest)]
