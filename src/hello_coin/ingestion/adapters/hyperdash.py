from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

HYPERDASH_GRAPHQL_URL = "https://api.hyperdash.com/graphql"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
GET_PERP_DELTAS_QUERY = (
    "query GetPerpDeltas($market: String!, $timeframe: DeltaTimeframe!) "
    "{ perpDeltas(market: $market, timeframe: $timeframe) "
    "{ market timeframe deltas { address current delta } } }"
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_position(address: str, position: dict[str, Any], timestamp: datetime) -> WhaleEvent | None:
    size = _number(position.get("szi"))
    position_value = _number(position.get("positionValue"))
    coin = position.get("coin")
    if size is None or position_value is None or not coin or size == 0:
        return None
    raw = dict(position)
    return WhaleEvent(
        source="hyperdash",
        timestamp=timestamp,
        chain_or_exchange="hyperliquid",
        symbol=str(coin).upper(),
        event_type="position",
        side="buy" if size > 0 else "sell",
        amount=abs(size),
        amount_usd=abs(position_value),
        wallet_address=address,
        dedup_key=f"position:{address}:{coin}:{size}:{timestamp.isoformat()}",
        raw=raw,
    )


class HyperdashAdapter(Adapter):
    name = "hyperdash"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self.coin_statuses: dict[str, dict[str, str | datetime | None]] = {
            coin.upper(): {"state": "STALE", "detail": "no successful poll", "last_success_at": None}
            for coin in settings.hyperdash_watch_coins
        }

    def is_configured(self) -> bool:
        return bool(self._settings.hyperdash_api_token and self._settings.hyperdash_watch_coins)

    async def fetch(self) -> list[WhaleEvent]:
        if not self.is_configured():
            for status in self.coin_statuses.values():
                status.update(state="NOT CONFIGURED", detail="HYPERDASH_API_TOKEN is not set")
            return []
        now = datetime.now(tz=UTC)
        events: list[WhaleEvent] = []
        addresses_by_coin: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for configured_coin in self._settings.hyperdash_watch_coins:
                coin = configured_coin.upper()
                try:
                    response = await client.post(
                        HYPERDASH_GRAPHQL_URL,
                        headers={"Authorization": f"Bearer {self._settings.hyperdash_api_token}"},
                        json={
                            "operationName": "GetPerpDeltas",
                            "variables": {
                                "market": coin,
                                "timeframe": self._settings.hyperdash_delta_timeframe,
                            },
                            "query": GET_PERP_DELTAS_QUERY,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    deltas = payload["data"]["perpDeltas"]["deltas"]
                    addresses = {
                        str(row["address"])
                        for row in deltas
                        if _number(row.get("current")) is not None
                        and abs(float(row["current"])) >= self._settings.hyperdash_min_delta_usd
                        and row.get("address")
                    }
                    addresses_by_coin[coin] = addresses
                    self.coin_statuses[coin] = {
                        "state": "LIVE",
                        "detail": f"{len(addresses)} qualifying wallet(s)",
                        "last_success_at": now,
                    }
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    self.coin_statuses[coin] = {
                        "state": "ERROR",
                        "detail": str(error),
                        "last_success_at": self.coin_statuses.get(coin, {}).get("last_success_at"),
                    }
            addresses = set().union(*addresses_by_coin.values()) if addresses_by_coin else set()
            for address in addresses:
                try:
                    response = await client.post(
                        HYPERLIQUID_INFO_URL,
                        json={"type": "clearinghouseState", "user": address},
                    )
                    response.raise_for_status()
                    positions = response.json().get("assetPositions", [])
                    for asset_position in positions:
                        position = asset_position.get("position", {})
                        coin = str(position.get("coin", "")).upper()
                        if coin not in addresses_by_coin:
                            continue
                        event = _parse_position(address, position, now)
                        if event and event.amount_usd >= self._settings.hyperdash_min_position_usd:
                            events.append(event)
                except (httpx.HTTPError, AttributeError, TypeError, ValueError) as error:
                    for coin, coin_addresses in addresses_by_coin.items():
                        if address in coin_addresses:
                            self.coin_statuses[coin] = {
                                "state": "ERROR",
                                "detail": f"Hyperliquid {address[:10]}: {error}",
                                "last_success_at": self.coin_statuses[coin].get("last_success_at"),
                            }
        return events
