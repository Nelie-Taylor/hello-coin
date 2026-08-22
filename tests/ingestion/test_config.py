from hello_coin.ingestion.config import Settings


def test_defaults_to_empty_watch_list(monkeypatch):
    monkeypatch.delenv("HYPERLIQUID_WATCH_ADDRESSES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == []


def test_parses_comma_separated_addresses(monkeypatch):
    monkeypatch.setenv("HYPERLIQUID_WATCH_ADDRESSES", "0xaaa, 0xbbb ,0xccc")

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == ["0xaaa", "0xbbb", "0xccc"]


def test_exchange_watch_symbols_defaults_to_btcusdt(monkeypatch):
    monkeypatch.delenv("EXCHANGE_WATCH_SYMBOLS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT"]


def test_exchange_watch_symbols_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("EXCHANGE_WATCH_SYMBOLS", "BTCUSDT, ETHUSDT ,SOLUSDT")

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_etherscan_api_key_defaults_to_none(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.etherscan_api_key is None


def test_etherscan_watch_addresses_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_WATCH_ADDRESSES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.etherscan_watch_addresses == []


def test_etherscan_watch_addresses_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("ETHERSCAN_WATCH_ADDRESSES", "0xaaa, 0xbbb ,0xccc")

    settings = Settings(_env_file=None)

    assert settings.etherscan_watch_addresses == ["0xaaa", "0xbbb", "0xccc"]
