import json

import httpx
import pytest
import respx

from hello_coin.ingestion.notifications import TelegramNotifier, format_skew_notification
from hello_coin.ingestion.position_skew import SkewAlert


def _alert(
    zone: str = "long_dominant",
    direction: str = "enter",
    long_usd: float = 820_000.0,
    short_usd: float = 180_000.0,
) -> SkewAlert:
    total = long_usd + short_usd
    return SkewAlert(
        coin="LINK",
        zone=zone,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        long_usd=long_usd,
        short_usd=short_usd,
        long_pct=long_usd / total,
        short_pct=short_usd / total,
    )


def test_enter_long_dominant_notification():
    title, body = format_skew_notification(_alert("long_dominant", "enter", 820_000, 180_000))

    assert title == "LINK: LONG áp đảo (82%)"
    assert body == "Long $820,000 vs Short $180,000 (tổng $1,000,000)"


def test_enter_short_dominant_notification():
    title, body = format_skew_notification(_alert("short_dominant", "enter", 180_000, 820_000))

    assert title == "LINK: SHORT áp đảo (82%)"
    assert body == "Short $820,000 vs Long $180,000 (tổng $1,000,000)"


def test_exit_long_dominant_notification():
    title, body = format_skew_notification(_alert("long_dominant", "exit", 680_000, 320_000))

    assert title == "LINK: LONG hạ nhiệt (68%)"
    assert body == "Long $680,000 vs Short $320,000 — có thể đang thoát lệnh"


def test_exit_short_dominant_notification():
    title, body = format_skew_notification(_alert("short_dominant", "exit", 320_000, 680_000))

    assert title == "LINK: SHORT hạ nhiệt (68%)"
    assert body == "Short $680,000 vs Long $320,000 — có thể đang thoát lệnh"


@pytest.mark.asyncio
@respx.mock
async def test_notify_posts_title_and_body_to_telegram_api():
    route = respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_alert())

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "chat456"
    assert "LINK: LONG áp đảo" in payload["text"]


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_bot_token():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier(None, "chat456", client=client)
        await notifier.notify(_alert())


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_chat_id():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", None, client=client)
        await notifier.notify(_alert())


@pytest.mark.asyncio
@respx.mock
async def test_notify_logs_delivery_failure_without_raising(caplog):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_alert())

    assert "failed to send Telegram notification" in caplog.text
