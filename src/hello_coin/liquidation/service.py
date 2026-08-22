from datetime import UTC, datetime

from hello_coin.liquidation.coinglass import fetch_heatmap
from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def _parse_bucket(row: dict) -> LiquidationBucket | None:
    """Field names here are an assumed shape — Coinglass's heatmap response
    has not been first-party-confirmed against a real key (same caveat as
    whale_alert.py/bitquery.py). Every access is defensive so a shape
    mismatch skips this row instead of raising."""
    price = row.get("price")
    notional_usd = row.get("leverage_value_usd")
    if price is None or notional_usd is None:
        return None
    return LiquidationBucket(price=float(price), notional_usd=float(notional_usd))


async def compute_snapshot(symbol: str, api_key: str) -> LiquidationSnapshot | None:
    payload = await fetch_heatmap(symbol, api_key)
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    current_price = data.get("current_price")
    rows = data.get("buckets")
    if current_price is None or not isinstance(rows, list):
        return None

    buckets = [b for row in rows if (b := _parse_bucket(row)) is not None]
    if not buckets:
        return None

    return LiquidationSnapshot(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        current_price=float(current_price),
        buckets=buckets,
    )
