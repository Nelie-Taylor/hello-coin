import logging
from typing import Protocol

import httpx

from hello_coin.ingestion.models import PositionChange

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationSink(Protocol):
    async def notify(self, change: PositionChange) -> None: ...


def _short_wallet(wallet: str | None) -> str:
    if not wallet:
        return "unknown wallet"
    if len(wallet) <= 10:
        return wallet
    return f"{wallet[:6]}...{wallet[-4:]}"


def format_position_notification(change: PositionChange) -> tuple[str, str]:
    event = change.event
    action = "opened" if change.action == "open" else "closed"
    side = {"buy": "LONG", "sell": "SHORT"}.get(event.side, "UNKNOWN")
    value = f"${event.amount_usd:,.0f}" if event.amount_usd is not None else "value unavailable"
    return f"Whale {action} position", f"{event.symbol} {side} · {value} · {_short_wallet(event.wallet_address)}"


class TelegramNotifier:
    """Deliver whale position-change alerts via the Telegram Bot API.

    A missing bot token or chat ID is treated as "not configured" — `notify()` is a
    silent no-op, matching every other optional credential in this codebase.
    """

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def notify(self, change: PositionChange) -> None:
        if not self._bot_token or not self._chat_id:
            return
        title, body = format_position_notification(change)
        try:
            response = await self._client.post(
                TELEGRAM_API_URL.format(token=self._bot_token),
                json={"chat_id": self._chat_id, "text": f"{title}\n{body}"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("failed to send Telegram notification")
