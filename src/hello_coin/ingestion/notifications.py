import logging
from typing import Protocol

import httpx

from hello_coin.ingestion.position_skew import SkewAlert

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationSink(Protocol):
    async def notify(self, alert: SkewAlert) -> None: ...


def format_skew_notification(alert: SkewAlert) -> tuple[str, str]:
    if alert.zone == "long_dominant":
        side_label, own_pct = "LONG", alert.long_pct
        comparison = f"Long ${alert.long_usd:,.0f} vs Short ${alert.short_usd:,.0f}"
    else:
        side_label, own_pct = "SHORT", alert.short_pct
        comparison = f"Short ${alert.short_usd:,.0f} vs Long ${alert.long_usd:,.0f}"
    percent = f"{own_pct:.0%}"
    if alert.direction == "enter":
        title = f"{alert.coin}: {side_label} áp đảo ({percent})"
        total = alert.long_usd + alert.short_usd
        body = f"{comparison} (tổng ${total:,.0f})"
    else:
        title = f"{alert.coin}: {side_label} hạ nhiệt ({percent})"
        body = f"{comparison} — có thể đang thoát lệnh"
    return title, body


class TelegramNotifier:
    """Deliver whale LONG/SHORT dominance alerts via the Telegram Bot API.

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

    async def notify(self, alert: SkewAlert) -> None:
        if not self._bot_token or not self._chat_id:
            return
        title, body = format_skew_notification(alert)
        try:
            response = await self._client.post(
                TELEGRAM_API_URL.format(token=self._bot_token),
                json={"chat_id": self._chat_id, "text": f"{title}\n{body}"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("failed to send Telegram notification")
