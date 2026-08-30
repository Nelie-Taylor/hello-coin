import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from hello_coin.ingestion.models import PositionChange, WhaleEvent
from hello_coin.ingestion.notifications import TelegramNotifier, format_position_notification


def _change(action: str = "open") -> PositionChange:
    return PositionChange(
        action=action,  # type: ignore[arg-type]
        event=WhaleEvent(
            source="hyperdash",
            timestamp=datetime(2026, 8, 29, tzinfo=UTC),
            chain_or_exchange="hyperliquid",
            symbol="SOL",
            event_type="position",
            side="sell",
            amount=5.0,
            amount_usd=125_000.0,
            wallet_address="0x1234567890abcdef",
            dedup_key="position:test",
        ),
    )


def test_open_notification_contains_action_coin_side_value_and_short_wallet():
    title, body = format_position_notification(_change())

    assert title == "Whale opened position"
    assert "SOL SHORT" in body
    assert "$125,000" in body
    assert "0x1234...cdef" in body


@pytest.mark.asyncio
@respx.mock
async def test_notify_posts_title_and_body_to_telegram_api():
    route = respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_change())

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "chat456"
    assert "Whale opened position" in payload["text"]
    assert "SOL SHORT" in payload["text"]


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_bot_token():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier(None, "chat456", client=client)
        await notifier.notify(_change())


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_chat_id():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", None, client=client)
        await notifier.notify(_change())


@pytest.mark.asyncio
@respx.mock
async def test_notify_logs_delivery_failure_without_raising(caplog):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_change())

    assert "failed to send Telegram notification" in caplog.text
