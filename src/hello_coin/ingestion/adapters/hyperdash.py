from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.position_skew import SkewAlert, SkewTracker

HYPERDASH_GRAPHQL_URL = "https://api.hyperdash.com/graphql"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERDASH_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://hyperdash.com",
    "Referer": "https://hyperdash.com/",
    "User-Agent": "Mozilla/5.0",
}
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
        self._skew_tracker = SkewTracker()
        self._active_wallets_by_coin: dict[str, set[str]] = {
            coin.upper(): set() for coin in settings.hyperdash_watch_coins
        }
        self._pending_skew_alerts: list[SkewAlert] = []

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
                        headers={
                            **HYPERDASH_HEADERS,
                            "Authorization": f"Bearer {self._settings.hyperdash_api_token}",
                        },
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
            coins_by_address: dict[str, set[str]] = {}
            for coin, candidate_addresses in addresses_by_coin.items():
                addresses = candidate_addresses | self._active_wallets_by_coin[coin]
                for address in addresses:
                    coins_by_address.setdefault(address, set()).add(coin)

            observed: dict[tuple[str, str], WhaleEvent] = {}
            confirmed: set[tuple[str, str]] = set()
            for address, coins in coins_by_address.items():
                try:
                    response = await client.post(
                        HYPERLIQUID_INFO_URL,
                        json={"type": "clearinghouseState", "user": address},
                    )
                    response.raise_for_status()
                    positions = response.json().get("assetPositions", [])
                    positions_by_coin = {
                        str(asset_position.get("position", {}).get("coin", "")).upper():
                        asset_position.get("position", {})
                        for asset_position in positions
                    }
                    for coin in coins:
                        key = (address, coin)
                        if address in self._active_wallets_by_coin[coin]:
                            confirmed.add(key)
                        event = _parse_position(address, positions_by_coin.get(coin, {}), now)
                        is_tracked = address in self._active_wallets_by_coin[coin]
                        if event and (is_tracked or event.amount_usd >= self._settings.hyperdash_min_position_usd):
                            observed[key] = event
                            if event.amount_usd >= self._settings.hyperdash_min_position_usd:
                                events.append(event)
                except (httpx.HTTPError, AttributeError, TypeError, ValueError) as error:
                    for coin in coins:
                        self.coin_statuses[coin] = {
                            "state": "ERROR",
                            "detail": f"Hyperliquid {address[:10]}: {error}",
                            "last_success_at": self.coin_statuses[coin].get("last_success_at"),
                        }

            self._update_skew(observed)
            for address, coin in confirmed:
                if (address, coin) not in observed:
                    self._active_wallets_by_coin[coin].discard(address)
            for address, coin in observed:
                self._active_wallets_by_coin[coin].add(address)
        return events

    def _update_skew(self, observed: dict[tuple[str, str], WhaleEvent]) -> None:
        totals: dict[str, tuple[float, float]] = {}
        for (_, coin), event in observed.items():
            long_usd, short_usd = totals.get(coin, (0.0, 0.0))
            amount_usd = event.amount_usd or 0.0
            if event.side == "buy":
                long_usd += amount_usd
            else:
                short_usd += amount_usd
            totals[coin] = (long_usd, short_usd)
        for configured_coin in self._settings.hyperdash_watch_coins:
            coin = configured_coin.upper()
            long_usd, short_usd = totals.get(coin, (0.0, 0.0))
            alert = self._skew_tracker.update(coin, long_usd, short_usd)
            if alert is not None:
                self._pending_skew_alerts.append(alert)

    def consume_skew_alerts(self) -> list[SkewAlert]:
        alerts = self._pending_skew_alerts
        self._pending_skew_alerts = []
        return alerts
