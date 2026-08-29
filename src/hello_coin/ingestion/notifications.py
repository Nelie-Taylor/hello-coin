import base64
import json
import logging
import platform
import subprocess
from collections.abc import Callable
from typing import Protocol

from hello_coin.ingestion.models import PositionChange

logger = logging.getLogger(__name__)


class NotificationSink(Protocol):
    def notify(self, change: PositionChange) -> None: ...


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


def _toast_script(title: str, body: str) -> str:
    payload = base64.b64encode(json.dumps({"title": title, "body": body}).encode()).decode()
    return f"""
$payload = '{payload}'
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
function Escape-ToastXml([string] $value) {{ return [Security.SecurityElement]::Escape($value) }}
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$(Escape-ToastXml $data.title)</text><text>$(Escape-ToastXml $data.body)</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('hello-coin').Show($toast)
""".strip()


class WindowsToastNotifier:
    """Deliver local system notifications without interrupting ingestion."""

    def __init__(self, run: Callable[..., object] = subprocess.run) -> None:
        self._run = run

    def notify(self, change: PositionChange) -> None:
        if platform.system() != "Windows":
            return
        title, body = format_position_notification(change)
        try:
            self._run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _toast_script(title, body)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            logger.exception("failed to send Windows toast")
