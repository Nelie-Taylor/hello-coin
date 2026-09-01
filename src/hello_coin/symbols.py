_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


def base_asset(symbol: str) -> str:
    """Strip a quote suffix ("BTCUSDT" -> "BTC") to bridge symbol conventions."""
    upper = symbol.upper()
    for suffix in _QUOTE_SUFFIXES:
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]
    return upper
