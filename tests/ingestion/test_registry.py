import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters


def test_build_adapters_includes_configured_hyperliquid():
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid"]


def test_build_adapters_skips_unconfigured_hyperliquid(caplog):
    settings = Settings(hyperliquid_watch_addresses=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert adapters == []
    assert "hyperliquid" in caplog.text
