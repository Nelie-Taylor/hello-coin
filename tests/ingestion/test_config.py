from hello_coin.ingestion.config import Settings


def test_defaults_to_empty_watch_list(monkeypatch):
    monkeypatch.delenv("HYPERLIQUID_WATCH_ADDRESSES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == []


def test_parses_comma_separated_addresses(monkeypatch):
    monkeypatch.setenv("HYPERLIQUID_WATCH_ADDRESSES", "0xaaa, 0xbbb ,0xccc")

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == ["0xaaa", "0xbbb", "0xccc"]
