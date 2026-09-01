import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters


def test_build_adapters_includes_configured_hyperdash():
    settings = Settings(
        _env_file=None,
        hyperdash_api_token="token",
        hyperdash_watch_coins=["LINK"],
    )

    assert [a.name for a in build_adapters(settings)] == ["hyperdash"]


def test_build_adapters_skips_unconfigured_hyperdash(caplog):
    settings = Settings(_env_file=None, hyperdash_api_token=None, hyperdash_watch_coins=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert adapters == []
    assert "hyperdash" in caplog.text
