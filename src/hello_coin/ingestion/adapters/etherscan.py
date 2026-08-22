from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ETHERSCAN_V2_API_URL = "https://api.etherscan.io/v2/api"

ETHERSCAN_CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {"chain_id": 1, "symbol": "ETH"},
    "bsc": {"chain_id": 56, "symbol": "BNB"},
    "polygon": {"chain_id": 137, "symbol": "MATIC"},
}


def _parse_tx(chain_key: str, symbol: str, address: str, row: dict[str, Any]) -> WhaleEvent:
    return WhaleEvent(
        source=f"etherscan_{chain_key}",
        timestamp=datetime.fromtimestamp(int(row["timeStamp"]), tz=UTC),
        chain_or_exchange=chain_key,
        symbol=symbol,
        event_type="transfer",
        side=None,
        amount=int(row["value"]) / 1e18,
        amount_usd=None,
        wallet_address=address,
        dedup_key=row["hash"],
        raw=row,
    )


class EtherscanAdapter(Adapter):
    """Watches a configured list of EVM wallet addresses for normal-transaction
    transfers, via Etherscan's unified V2 API. One instance per chain
    (`chain_key` selects `chainid`); all instances share the same API key and
    watch-address list. Requires a free Etherscan API key.
    """

    poll_interval_seconds = 60

    def __init__(self, settings: Settings, chain_key: str) -> None:
        super().__init__()
        self._settings = settings
        self._chain_key = chain_key
        self._chain_id = ETHERSCAN_CHAINS[chain_key]["chain_id"]
        self._symbol = ETHERSCAN_CHAINS[chain_key]["symbol"]
        self.name = f"etherscan_{chain_key}"
        self._last_seen_block: dict[str, int] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.etherscan_api_key) and bool(
            self._settings.etherscan_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.etherscan_watch_addresses:
                start_block = self._last_seen_block.get(address, 0)
                response = await client.get(
                    ETHERSCAN_V2_API_URL,
                    params={
                        "chainid": self._chain_id,
                        "module": "account",
                        "action": "txlist",
                        "address": address,
                        "startblock": start_block,
                        "endblock": 99999999,
                        "page": 1,
                        "offset": 100,
                        "sort": "asc",
                        "apikey": self._settings.etherscan_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result")
                if payload.get("status") == "0":
                    if isinstance(result, str):
                        raise RuntimeError(
                            f"Etherscan API error for chain {self._chain_id}: {result}"
                        )
                    continue
                rows = result or []
                for row in rows:
                    if row.get("isError") == "0":
                        events.append(_parse_tx(self._chain_key, self._symbol, address, row))
                if rows:
                    self._last_seen_block[address] = max(
                        int(row["blockNumber"]) for row in rows
                    ) + 1
        return events
