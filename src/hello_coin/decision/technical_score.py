from typing import Any


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _score_rsi(rsi: float | None) -> float | None:
    if rsi is None:
        return None
    return _clip((50 - rsi) / 50, -1.0, 1.0)


def _score_macd(histogram: float | None) -> float | None:
    if histogram is None:
        return None
    if histogram > 0:
        return 1.0
    if histogram < 0:
        return -1.0
    return 0.0


def _score_bollinger(
    close_price: float | None, bb_upper: float | None, bb_middle: float | None
) -> float | None:
    if close_price is None or bb_upper is None or bb_middle is None:
        return None
    if bb_upper == bb_middle:
        return None
    return _clip((bb_middle - close_price) / (bb_upper - bb_middle), -1.0, 1.0)


def _score_ema(close_price: float | None, ema: float | None) -> float | None:
    if close_price is None or ema is None:
        return None
    if close_price > ema:
        return 1.0
    if close_price < ema:
        return -1.0
    return 0.0


def compute_technical_score(snapshot: dict[str, Any]) -> float | None:
    close_price = snapshot.get("close_price")
    components = [
        c
        for c in (
            _score_rsi(snapshot.get("rsi")),
            _score_macd(snapshot.get("macd_histogram")),
            _score_bollinger(close_price, snapshot.get("bb_upper"), snapshot.get("bb_middle")),
            _score_ema(close_price, snapshot.get("ema")),
        )
        if c is not None
    ]
    if not components:
        return None
    return sum(components) / len(components)
