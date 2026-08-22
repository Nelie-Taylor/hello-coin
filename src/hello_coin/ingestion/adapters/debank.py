from datetime import UTC, datetime

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

DEBANK_TOTAL_BALANCE_URL = "https://pro-openapi.debank.com/v1/user/total_balance"


class DebankAdapter(Adapter):
    """Polls DeBank Cloud for a watched wallet's total portfolio value across
    all chains — a snapshot, recorded as a `position` event. Needs a paid
    DeBank Cloud AccessKey (unit-based billing).
    """

    name = "debank"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.debank_access_key) and bool(
            self._settings.debank_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.debank_watch_addresses:
                response = await client.get(
                    DEBANK_TOTAL_BALANCE_URL,
                    params={"id": address},
                    headers={"AccessKey": self._settings.debank_access_key},
                )
                response.raise_for_status()
                payload = response.json()
                total_usd_value = float(payload["total_usd_value"])
                now = datetime.now(tz=UTC)
                events.append(
                    WhaleEvent(
                        source="debank",
                        timestamp=now,
                        chain_or_exchange="multi-chain",
                        symbol="USD",
                        event_type="position",
                        side=None,
                        amount=total_usd_value,
                        amount_usd=total_usd_value,
                        wallet_address=address,
                        dedup_key=f"{address}:{now.isoformat()}",
                        raw=payload,
                    )
                )
        return events
