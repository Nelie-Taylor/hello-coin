from datetime import UTC, datetime

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

OKX_LONG_SHORT_RATIO_URL = (
    "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio-contract"
)


def to_okx_inst_id(symbol: str) -> str:
    if not symbol.endswith("USDT"):
        raise ValueError(f"unsupported symbol for OKX conversion: {symbol}")
    base = symbol[: -len("USDT")]
    return f"{base}-USDT-SWAP"


class OkxAdapter(Adapter):
    """Polls OKX's public long/short account-ratio endpoint for USDT-margined
    swaps. No API key needed.
    """

    name = "okx"
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
                inst_id = to_okx_inst_id(symbol)
                response = await client.get(
                    OKX_LONG_SHORT_RATIO_URL, params={"instId": inst_id, "limit": 1}
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                if not rows:
                    continue
                latest = max(rows, key=lambda row: int(row[0]))
                timestamp_ms = int(latest[0])
                metrics.append(
                    WhaleMetric(
                        source="okx",
                        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
                        symbol=symbol,
                        metric_name="long_short_account_ratio",
                        value=float(latest[1]),
                        dedup_key=f"{symbol}:{timestamp_ms}",
                        raw={"instId": inst_id, "timestamp": latest[0], "ratio": latest[1]},
                    )
                )
        return metrics
