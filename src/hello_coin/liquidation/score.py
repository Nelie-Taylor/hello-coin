from hello_coin.liquidation.models import LiquidationSnapshot


def compute_liquidation_score(
    snapshot: LiquidationSnapshot, proximity_pct: float = 0.10
) -> float | None:
    """Weighs nearby short-liquidation clusters (bullish magnet — price tends
    to get pulled up to sweep them) against nearby long-liquidation clusters
    (bearish magnet) into a single [-1, 1] score. Clusters farther than
    `proximity_pct` away don't inform near-term entry/exit decisions and are
    excluded; a bucket exactly at the current price has no defined side and
    is excluded too."""
    current_price = snapshot.current_price
    weighted_long = 0.0
    weighted_short = 0.0
    for bucket in snapshot.buckets:
        distance_pct = abs(bucket.price - current_price) / current_price
        if distance_pct == 0 or distance_pct > proximity_pct:
            continue
        weight = bucket.notional_usd / distance_pct
        if bucket.price < current_price:
            weighted_long += weight
        else:
            weighted_short += weight

    total = weighted_long + weighted_short
    if total == 0:
        return None
    return (weighted_short - weighted_long) / total


def nearest_clusters(
    snapshot: LiquidationSnapshot, n: int = 2
) -> dict[str, list[tuple[float, float]]]:
    """Top-N clusters per side by notional value, as (price, notional_usd)
    pairs — concrete levels for the decision LLM's entry/exit/stop-loss
    context, not a score. Not proximity-filtered: a large cluster further
    out can still be a meaningful target."""
    current_price = snapshot.current_price
    long_clusters = sorted(
        (b for b in snapshot.buckets if b.price < current_price),
        key=lambda b: b.notional_usd,
        reverse=True,
    )[:n]
    short_clusters = sorted(
        (b for b in snapshot.buckets if b.price > current_price),
        key=lambda b: b.notional_usd,
        reverse=True,
    )[:n]
    return {
        "long_below": [(b.price, b.notional_usd) for b in long_clusters],
        "short_above": [(b.price, b.notional_usd) for b in short_clusters],
    }
