"""Pure, framework-free formatting helpers shared by the dashboard templates."""

import json
from datetime import datetime


def format_number(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, int | float):
        return f"{value:,.4f}"
    return str(value)


def format_wallet(value: object) -> str:
    text = str(value or "N/A")
    return text if len(text) <= 14 else f"{text[:7]}…{text[-5:]}"


def format_age(value: object, now: datetime) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value))
        return f"{max(0, int((now - timestamp).total_seconds()))}s"
    except (TypeError, ValueError):
        return "N/A"


def format_direction(side: object) -> str:
    if side == "buy":
        return "LONG (BUY)"
    if side == "sell":
        return "SHORT (SELL)"
    return "N/A"


def format_event_leverage(raw: object) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return "N/A"
    if not isinstance(raw, dict):
        return "N/A"
    leverage = raw.get("leverage")
    if isinstance(leverage, dict):
        leverage = leverage.get("value")
    if isinstance(leverage, int | float):
        return f"{leverage:g}x"
    return "N/A"


def format_position_leverage(raw: object) -> str:
    if not isinstance(raw, dict):
        return "N/A"
    leverage = raw.get("leverage")
    if not isinstance(leverage, dict):
        return "N/A"
    value = leverage.get("value")
    if not isinstance(value, int | float):
        return "N/A"
    kind = leverage.get("type")
    return f"{kind} · {value:g}x" if kind else f"{value:g}x"


def position_side_label(side: object) -> str:
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    return "N/A"


def coin_panel_id(coin: str) -> str:
    return "coin-" + "".join(character.lower() if character.isalnum() else "-" for character in coin)
