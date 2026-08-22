from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

NANSEN_TRANSACTIONS_URL = "https://api.nansen.ai/api/v1/profiler/address/transactions"


def _parse_transaction(address: str, row: dict[str, Any]) -> WhaleEvent | None:
    tokens_sent = row.get("tokens_sent") or []
    tokens_received = row.get("tokens_received") or []
    if tokens_sent:
        token, side = tokens_sent[0], "sell"
    elif tokens_received:
        token, side = tokens_received[0], "buy"
    else:
        return None
    return WhaleEvent(
        source="nansen",
        timestamp=datetime.fromisoformat(row["block_timestamp"]),
        chain_or_exchange=row["chain"],
        symbol=token["token_symbol"],
        event_type="transfer",
        side=side,
        amount=float(token["token_amount"]),
        amount_usd=float(row["volume_usd"]) if row.get("volume_usd") is not None else None,
        wallet_address=address,
        dedup_key=row["transaction_hash"],
        raw=row,
    )


class NansenAdapter(Adapter):
    """Watches a configured list of wallet addresses for labeled on-chain
    transactions via Nansen's Address Transactions endpoint. Needs a paid
    Nansen API key.
    """

    name = "nansen"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen: dict[str, datetime] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.nansen_api_key) and bool(
            self._settings.nansen_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        now = datetime.now(tz=UTC)
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.nansen_watch_addresses:
                start = self._last_seen.get(address, now - timedelta(hours=1))
                response = await client.post(
                    NANSEN_TRANSACTIONS_URL,
                    headers={"apikey": self._settings.nansen_api_key},
                    json={
                        "address": address,
                        "chain": "ethereum",
                        "date": {"from": start.isoformat(), "to": now.isoformat()},
                    },
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                for row in rows:
                    event = _parse_transaction(address, row)
                    if event is not None:
                        events.append(event)
                self._last_seen[address] = now
        return events
