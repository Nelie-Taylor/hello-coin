"""Pure, framework-free formatting helpers shared by the dashboard templates."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from hello_coin.ingestion.position_skew import compute_skew


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


def side_class(side: object) -> str:
    if side == "buy":
        return "side-long"
    if side == "sell":
        return "side-short"
    return ""


def coin_skew(rows: Sequence[dict[str, Any]]) -> tuple[str, str, str]:
    """LONG/SHORT dominance label, CSS class, and dominant-side weighted average entry
    price for a coin's position rows.

    Uses the same `compute_skew()` percentages that drive the Telegram dominance
    alerts, so the number shown here always matches what triggers a notification. The
    average entry price is weighted by `amount_usd` and computed only over rows on
    whichever side is currently dominant (matching the notified side).
    """
    long_usd = sum((row.get("amount_usd") or 0.0) for row in rows if row.get("side") == "buy")
    short_usd = sum((row.get("amount_usd") or 0.0) for row in rows if row.get("side") == "sell")
    if long_usd + short_usd <= 0:
        return "", "", ""
    long_pct, short_pct = compute_skew(long_usd, short_usd)
    dominant_side = "buy" if long_pct >= short_pct else "sell"
    label, css_class = (
        (f"LONG {long_pct:.0%}", "side-long")
        if dominant_side == "buy"
        else (f"SHORT {short_pct:.0%}", "side-short")
    )
    return label, css_class, _weighted_average_entry(rows, dominant_side)


def _weighted_average_entry(rows: Sequence[dict[str, Any]], side: str) -> str:
    weighted_sum = 0.0
    weight_total = 0.0
    for row in rows:
        if row.get("side") != side:
            continue
        raw = row.get("raw") or {}
        try:
            entry_px = float(raw.get("entryPx"))
        except (TypeError, ValueError):
            continue
        weight = row.get("amount_usd") or 0.0
        weighted_sum += entry_px * weight
        weight_total += weight
    if weight_total <= 0:
        return ""
    return format_number(weighted_sum / weight_total)
