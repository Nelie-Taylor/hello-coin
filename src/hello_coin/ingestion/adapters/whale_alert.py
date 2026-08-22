import time
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

WHALE_ALERT_TRANSACTIONS_URL = "https://api.whale-alert.io/v1/transactions"
ONE_HOUR_SECONDS = 3600


def _parse_transaction(row: dict[str, Any]) -> WhaleEvent | None:
    """Field names here are the best-documented shape found (see the plan's
    'Verified live' note) but are NOT first-party-confirmed — every access is
    defensive so a shape mismatch skips this row instead of raising."""
    tx_hash = row.get("hash")
    timestamp = row.get("timestamp")
    amount = row.get("amount")
    if tx_hash is None or timestamp is None or amount is None:
        return None
    to_address = (row.get("to") or {}).get("address")
    return WhaleEvent(
        source="whale_alert",
        timestamp=datetime.fromtimestamp(int(timestamp), tz=UTC),
        chain_or_exchange=row.get("blockchain", "unknown"),
        symbol=row.get("symbol", "unknown"),
        event_type="transfer",
        side=None,
        amount=float(amount),
        amount_usd=float(row["amount_usd"]) if row.get("amount_usd") is not None else None,
        wallet_address=to_address,
        dedup_key=tx_hash,
        raw=row,
    )


class WhaleAlertAdapter(Adapter):
    """Polls Whale Alert's global large-transaction feed (no watch-address
    list needed — every chain, filtered by `min_value`). Needs a paid Whale
    Alert API key. See the plan's confidence note: response field names are
    secondhand, parsed defensively.
    """

    name = "whale_alert"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen_ts = int(time.time()) - ONE_HOUR_SECONDS

    def is_configured(self) -> bool:
        return bool(self._settings.whale_alert_api_key)

    async def fetch(self) -> list[WhaleEvent]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                WHALE_ALERT_TRANSACTIONS_URL,
                params={
                    "api_key": self._settings.whale_alert_api_key,
                    "start": self._last_seen_ts,
                    "min_value": self._settings.whale_alert_min_value_usd,
                },
            )
            response.raise_for_status()
            rows = response.json().get("transactions", [])
            events = [event for row in rows if (event := _parse_transaction(row)) is not None]
            timestamps = [row["timestamp"] for row in rows if row.get("timestamp") is not None]
            if timestamps:
                self._last_seen_ts = max(timestamps) + 1
            return events
