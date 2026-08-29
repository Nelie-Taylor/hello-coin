import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters

ALL_NAMES = [
    "hyperliquid",
    "binance",
    "okx",
    "bybit",
    "bitget",
    "etherscan_ethereum",
    "etherscan_bsc",
    "etherscan_polygon",
    "cryptoquant",
    "debank",
    "nansen",
    "whale_alert",
    "bitquery",
]

UNCONFIGURED_CREDENTIALS = {
    "etherscan_api_key": None,
    "etherscan_watch_addresses": [],
    "cryptoquant_api_key": None,
    "debank_access_key": None,
    "debank_watch_addresses": [],
    "nansen_api_key": None,
    "nansen_watch_addresses": [],
    "whale_alert_api_key": None,
    "bitquery_access_token": None,
}


def test_build_adapters_includes_all_configured_sources():
    settings = Settings(
        _env_file=None,
        hyperliquid_watch_addresses=["0xabc"],
        etherscan_api_key="test-key",
        etherscan_watch_addresses=["0xabc"],
        cryptoquant_api_key="test-key",
        debank_access_key="test-key",
        debank_watch_addresses=["0xabc"],
        nansen_api_key="test-key",
        nansen_watch_addresses=["0xabc"],
        whale_alert_api_key="test-key",
        bitquery_access_token="test-token",
    )

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ALL_NAMES


def test_build_adapters_includes_configured_hyperdash():
    settings = Settings(
        _env_file=None,
        hyperdash_api_token="token",
        hyperdash_watch_coins=["LINK"],
        hyperliquid_watch_addresses=[],
        exchange_watch_symbols=[],
        **UNCONFIGURED_CREDENTIALS,
    )

    assert [a.name for a in build_adapters(settings)] == ["hyperdash"]


def test_build_adapters_skips_unconfigured_hyperliquid_but_keeps_exchange_adapters(caplog):
    settings = Settings(_env_file=None, hyperliquid_watch_addresses=[], **UNCONFIGURED_CREDENTIALS)

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["binance", "okx", "bybit", "bitget"]
    assert "hyperliquid" in caplog.text


def test_build_adapters_skips_all_exchange_adapters_when_no_symbols(caplog):
    settings = Settings(
        _env_file=None,
        hyperliquid_watch_addresses=["0xabc"],
        exchange_watch_symbols=[],
        **UNCONFIGURED_CREDENTIALS,
    )

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid"]
    for exchange in ("binance", "okx", "bybit", "bitget"):
        assert exchange in caplog.text


def test_build_adapters_skips_etherscan_chains_when_not_configured(caplog):
    settings = Settings(_env_file=None, hyperliquid_watch_addresses=["0xabc"], **UNCONFIGURED_CREDENTIALS)

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert "etherscan_ethereum" not in [a.name for a in adapters]
    for chain in ("etherscan_ethereum", "etherscan_bsc", "etherscan_polygon"):
        assert chain in caplog.text


def test_build_adapters_skips_freemium_sources_when_not_configured(caplog):
    settings = Settings(_env_file=None, hyperliquid_watch_addresses=["0xabc"], **UNCONFIGURED_CREDENTIALS)

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    names = [a.name for a in adapters]
    for source in ("cryptoquant", "debank", "nansen", "whale_alert", "bitquery"):
        assert source not in names
        assert source in caplog.text
