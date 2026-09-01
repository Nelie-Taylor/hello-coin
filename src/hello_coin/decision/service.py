from datetime import UTC, datetime
from typing import Any

from hello_coin.decision.llm import request_decision
from hello_coin.decision.models import Decision
from hello_coin.decision.technical_score import compute_technical_score
from hello_coin.liquidation.score import compute_liquidation_score, nearest_clusters

SYSTEM_PROMPT = (
    "You are a crypto trading decision assistant for the hello-coin system. Technical "
    "indicators and the liquidation heatmap are combined into weighted_score: when both "
    "signals are available, technical carries 60% and liquidation 40% of the weight; when "
    "the liquidation signal is unavailable, the technical score carries 100% — treat "
    "weighted_score's value as authoritative rather than assuming a fixed split. Scores "
    "range from -1 (strongly bearish) to +1 (strongly bullish); a missing score means that "
    "data source had nothing usable this cycle, not that it's neutral — factor the gap into "
    "your confidence rather than ignoring it. When liquidation cluster prices are provided, "
    "use them as concrete levels for entry/exit timing and stop-loss/take-profit placement, "
    "not just for direction. Always call the decide tool."
)


def _build_user_message(
    symbol: str,
    technical_score: float | None,
    liquidation_score: float | None,
    weighted_score: float | None,
    snapshot: dict[str, Any] | None,
    clusters: dict[str, list[tuple[float, float]]] | None,
) -> str:
    lines = [f"Symbol: {symbol}"]
    lines.append(
        f"technical_score: {technical_score if technical_score is not None else 'unavailable'}"
    )
    lines.append(
        "liquidation_score: "
        f"{liquidation_score if liquidation_score is not None else 'unavailable'}"
    )
    if weighted_score is not None:
        weighted_display = str(weighted_score)
    else:
        weighted_display = "unavailable (no technical signal this cycle)"
    lines.append(f"weighted_score: {weighted_display}")
    if snapshot is not None:
        lines.append(
            "Latest technical readings: "
            f"close={snapshot.get('close_price')}, rsi={snapshot.get('rsi')}, "
            f"macd_histogram={snapshot.get('macd_histogram')}, "
            f"bollinger=({snapshot.get('bb_lower')}, {snapshot.get('bb_middle')}, "
            f"{snapshot.get('bb_upper')}), ema={snapshot.get('ema')}, atr={snapshot.get('atr')}"
        )
    if clusters is not None:
        lines.append(
            "Nearest liquidation clusters (price, notional_usd): "
            f"long_below={clusters['long_below']}, short_above={clusters['short_above']}"
        )
    return "\n".join(lines)


async def compute_decision(
    symbol: str,
    timeframe: str,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    liquidation_proximity_pct: float = 0.10,
) -> Decision:
    snapshot = technical_storage.latest_snapshot(symbol, timeframe)
    technical_score = compute_technical_score(snapshot) if snapshot is not None else None

    liq_snapshot = liquidation_storage.latest_snapshot(symbol)
    liquidation_score = (
        compute_liquidation_score(liq_snapshot, liquidation_proximity_pct)
        if liq_snapshot is not None
        else None
    )
    clusters = nearest_clusters(liq_snapshot) if liq_snapshot is not None else None

    if technical_score is not None and liquidation_score is not None:
        weighted_score = 0.60 * technical_score + 0.40 * liquidation_score
    elif technical_score is not None:
        weighted_score = technical_score
    else:
        weighted_score = None

    user_message = _build_user_message(
        symbol,
        technical_score,
        liquidation_score,
        weighted_score,
        snapshot,
        clusters,
    )
    result = await request_decision(
        client=anthropic_client, model=model, system=SYSTEM_PROMPT, user_message=user_message
    )

    return Decision(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        technical_score=technical_score,
        liquidation_score=liquidation_score,
        weighted_score=weighted_score,
        action=result["action"],
        confidence=float(result["confidence"]),
        reasoning=result["reasoning"],
        raw=result,
    )
