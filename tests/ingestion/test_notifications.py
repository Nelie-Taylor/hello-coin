from datetime import UTC, datetime

from hello_coin.ingestion.models import PositionChange, WhaleEvent
from hello_coin.ingestion.notifications import WindowsToastNotifier, format_position_notification


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


def test_open_toast_contains_action_coin_side_value_and_short_wallet():
    title, body = format_position_notification(_change())

    assert title == "Whale opened position"
    assert "SOL SHORT" in body
    assert "$125,000" in body
    assert "0x1234...cdef" in body


def test_notifier_skips_non_windows_platform(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr("hello_coin.ingestion.notifications.platform.system", lambda: "Linux")

    WindowsToastNotifier(run=calls.append).notify(_change())

    assert calls == []


def test_notifier_logs_delivery_failure_without_raising(monkeypatch, caplog):
    def fail(_command: object, **_kwargs: object) -> None:
        raise OSError("PowerShell missing")

    monkeypatch.setattr("hello_coin.ingestion.notifications.platform.system", lambda: "Windows")

    WindowsToastNotifier(run=fail).notify(_change())

    assert "failed to send Windows toast" in caplog.text
