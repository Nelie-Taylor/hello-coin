import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters


def test_build_adapters_includes_all_configured_sources():
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid", "binance", "okx", "bybit", "bitget"]


def test_build_adapters_skips_unconfigured_hyperliquid_but_keeps_exchange_adapters(caplog):
    settings = Settings(hyperliquid_watch_addresses=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["binance", "okx", "bybit", "bitget"]
    assert "hyperliquid" in caplog.text


def test_build_adapters_skips_all_exchange_adapters_when_no_symbols(caplog):
    settings = Settings(hyperliquid_watch_addresses=["0xabc"], exchange_watch_symbols=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid"]
    for exchange in ("binance", "okx", "bybit", "bitget"):
        assert exchange in caplog.text
