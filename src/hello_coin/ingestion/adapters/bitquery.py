from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

BITQUERY_GRAPHQL_URL = "https://streaming.bitquery.io/graphql"

_TRANSFERS_QUERY = """
{
  EVM(network: eth, dataset: combined) {
    Transfers(limit: {count: 20}, orderBy: {descending: Block_Time},
               where: {Transfer: {AmountInUSD: {ge: "%(min_value)s"}}}) {
      Transfer {
        Amount
        AmountInUSD
        Currency { Fungible Name ProtocolName Symbol }
        Sender
        Receiver
        Success
        Type
        Id
      }
    }
  }
}
"""


def _parse_transfer(row: dict[str, Any]) -> WhaleEvent:
    transfer = row["Transfer"]
    return WhaleEvent(
        source="bitquery",
        timestamp=datetime.now(tz=UTC),
        chain_or_exchange="ethereum",
        symbol=transfer["Currency"]["Symbol"],
        event_type="transfer",
        side=None,
        amount=float(transfer["Amount"]),
        amount_usd=float(transfer["AmountInUSD"]) if transfer.get("AmountInUSD") else None,
        wallet_address=transfer["Receiver"],
        dedup_key=transfer["Id"],
        raw=transfer,
    )


class BitqueryAdapter(Adapter):
    """Polls Bitquery's GraphQL API for large Ethereum transfers above
    `bitquery_min_value_usd`. Needs a Bitquery OAuth access token. See the
    plan's confidence note: query field set is well-sourced but not
    independently re-verified against a live 200 response.
    """

    name = "bitquery"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.bitquery_access_token)

    async def fetch(self) -> list[WhaleEvent]:
        query = _TRANSFERS_QUERY % {"min_value": self._settings.bitquery_min_value_usd}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                BITQUERY_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {self._settings.bitquery_access_token}"},
                json={"query": query},
            )
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise RuntimeError(f"Bitquery GraphQL error: {payload['errors']}")
            rows = payload.get("data", {}).get("EVM", {}).get("Transfers", [])
            return [_parse_transfer(row) for row in rows]
