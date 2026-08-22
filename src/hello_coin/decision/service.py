from datetime import UTC, datetime, timedelta
from typing import Any

from hello_coin.decision.llm import request_decision
from hello_coin.decision.models import Decision
from hello_coin.decision.technical_score import compute_technical_score
from hello_coin.decision.whale_score import base_asset, compute_whale_score

SYSTEM_PROMPT = (
    "You are a crypto trading decision assistant for the hello-coin system. Whale activity "
    "carries roughly 70% of the decision weight and technical indicators roughly 30% — treat "
    "the provided whale_score and technical_score accordingly, not as equally weighted inputs. "
    "Scores range from -1 (strongly bearish) to +1 (strongly bullish); a missing score means "
    "that data source had nothing usable this cycle, not that it's neutral — factor the gap "
    "into your confidence rather than ignoring it. Always call the decide tool."
)


def _build_user_message(
    symbol: str,
    whale_score: float | None,
    technical_score: float | None,
    weighted_score: float | None,
    snapshot: dict[str, Any] | None,
) -> str:
    lines = [f"Symbol: {symbol}"]
    lines.append(f"whale_score: {whale_score if whale_score is not None else 'unavailable'}")
    lines.append(
        f"technical_score: {technical_score if technical_score is not None else 'unavailable'}"
    )
    lines.append(
        f"weighted_score (0.7*whale + 0.3*technical): "
        f"{weighted_score if weighted_score is not None else 'unavailable (one or both inputs missing)'}"
    )
    if snapshot is not None:
        lines.append(
            "Latest technical readings: "
            f"close={snapshot.get('close_price')}, rsi={snapshot.get('rsi')}, "
            f"macd_histogram={snapshot.get('macd_histogram')}, "
            f"bollinger=({snapshot.get('bb_lower')}, {snapshot.get('bb_middle')}, "
            f"{snapshot.get('bb_upper')}), ema={snapshot.get('ema')}, atr={snapshot.get('atr')}"
        )
    return "\n".join(lines)


async def compute_decision(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
) -> Decision:
    since = datetime.now(tz=UTC) - timedelta(hours=whale_lookback_hours)
    asset = base_asset(symbol)

    events = whale_storage.recent_events(asset, since)
    metrics = whale_storage.recent_metrics(symbol, since) + whale_storage.recent_metrics(
        asset, since
    )
    whale_score = compute_whale_score(events, metrics)

    snapshot = technical_storage.latest_snapshot(symbol, timeframe)
    technical_score = compute_technical_score(snapshot) if snapshot is not None else None

    weighted_score = (
        0.7 * whale_score + 0.3 * technical_score
        if whale_score is not None and technical_score is not None
        else None
    )

    user_message = _build_user_message(symbol, whale_score, technical_score, weighted_score, snapshot)
    result = await request_decision(
        client=anthropic_client, model=model, system=SYSTEM_PROMPT, user_message=user_message
    )

    return Decision(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        whale_score=whale_score,
        technical_score=technical_score,
        weighted_score=weighted_score,
        action=result["action"],
        confidence=float(result["confidence"]),
        reasoning=result["reasoning"],
        raw=result,
    )
