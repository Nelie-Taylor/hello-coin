_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


def base_asset(symbol: str) -> str:
    upper = symbol.upper()
    for suffix in _QUOTE_SUFFIXES:
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]
    return upper


def _volume_bias(events: list[dict]) -> float | None:
    relevant = [
        e for e in events if e.get("side") in ("buy", "sell") and e.get("amount_usd") is not None
    ]
    if not relevant:
        return None
    buy_usd = sum(e["amount_usd"] for e in relevant if e["side"] == "buy")
    sell_usd = sum(e["amount_usd"] for e in relevant if e["side"] == "sell")
    total = buy_usd + sell_usd
    return (buy_usd - sell_usd) / total if total > 0 else 0.0


def _ratio_bias(metrics: list[dict]) -> float | None:
    values = [
        m["value"]
        for m in metrics
        if m.get("metric_name", "").endswith("ratio")
        and m.get("value") is not None
        and m["value"] > -1
    ]
    if not values:
        return None
    normalized = [(v - 1) / (v + 1) for v in values]
    return sum(normalized) / len(normalized)


def compute_whale_score(events: list[dict], metrics: list[dict]) -> float | None:
    components = [c for c in (_volume_bias(events), _ratio_bias(metrics)) if c is not None]
    if not components:
        return None
    return sum(components) / len(components)
