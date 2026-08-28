import time
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
ONE_HOUR_MS = 3_600_000


def _parse_fill(address: str, fill: dict[str, Any]) -> WhaleEvent:
    side = "buy" if fill["side"] == "B" else "sell"
    price = float(fill["px"])
    size = float(fill["sz"])
    return WhaleEvent(
        source="hyperliquid",
        timestamp=datetime.fromtimestamp(fill["time"] / 1000, tz=UTC),
        chain_or_exchange="hyperliquid",
        symbol=fill["coin"],
        event_type="fill",
        side=side,
        amount=size,
        amount_usd=price * size,
        wallet_address=address,
        dedup_key=f"{fill['hash']}:{fill['tid']}",
        raw=fill,
    )


def _parse_position(
    address: str, asset_position: dict[str, Any], timestamp: datetime
) -> WhaleEvent | None:
    position = asset_position["position"]
    size = float(position["szi"])
    if size == 0:
        return None
    leverage = position.get("leverage")
    leverage_value = leverage.get("value") if isinstance(leverage, dict) else None
    return WhaleEvent(
        source="hyperliquid",
        timestamp=timestamp,
        chain_or_exchange="hyperliquid",
        symbol=position["coin"],
        event_type="position",
        side="buy" if size > 0 else "sell",
        amount=abs(size),
        amount_usd=abs(float(position["positionValue"])),
        wallet_address=address,
        dedup_key=f"position:{address}:{position['coin']}:{size}:{leverage_value}",
        raw=position,
    )


class HyperliquidAdapter(Adapter):
    """Tracks fills for a configured watchlist of Hyperliquid wallet addresses.

    No API key needed — Hyperliquid's info endpoint is public and unauthenticated.
    """

    name = "hyperliquid"
    poll_interval_seconds = 20

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen_ms: dict[str, int] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.hyperliquid_watch_addresses)

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.hyperliquid_watch_addresses:
                start_time = self._last_seen_ms.get(
                    address, int(time.time() * 1000) - ONE_HOUR_MS
                )
                response = await client.post(
                    HYPERLIQUID_INFO_URL,
                    json={"type": "userFillsByTime", "user": address, "startTime": start_time},
                )
                response.raise_for_status()
                fills = response.json()
                for fill in fills:
                    events.append(_parse_fill(address, fill))
                positions_response = await client.post(
                    HYPERLIQUID_INFO_URL,
                    json={"type": "clearinghouseState", "user": address},
                )
                positions_response.raise_for_status()
                now = datetime.now(tz=UTC)
                for asset_position in positions_response.json().get("assetPositions", []):
                    position = _parse_position(address, asset_position, now)
                    if position is not None:
                        events.append(position)
                if fills:
                    self._last_seen_ms[address] = max(fill["time"] for fill in fills) + 1
        return events
