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


def test_freemium_settings_default_to_unconfigured(monkeypatch):
    for var in (
        "DEBANK_ACCESS_KEY",
        "DEBANK_WATCH_ADDRESSES",
        "CRYPTOQUANT_API_KEY",
        "NANSEN_API_KEY",
        "NANSEN_WATCH_ADDRESSES",
        "WHALE_ALERT_API_KEY",
        "BITQUERY_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.debank_access_key is None
    assert settings.debank_watch_addresses == []
    assert settings.cryptoquant_api_key is None
    assert settings.nansen_api_key is None
    assert settings.nansen_watch_addresses == []
    assert settings.whale_alert_api_key is None
    assert settings.whale_alert_min_value_usd == 500_000
    assert settings.bitquery_access_token is None
    assert settings.bitquery_min_value_usd == 500_000


def test_debank_and_nansen_watch_addresses_parse_comma_separated(monkeypatch):
    monkeypatch.setenv("DEBANK_WATCH_ADDRESSES", "0xaaa, 0xbbb")
    monkeypatch.setenv("NANSEN_WATCH_ADDRESSES", "0xccc, 0xddd")

    settings = Settings(_env_file=None)

    assert settings.debank_watch_addresses == ["0xaaa", "0xbbb"]
    assert settings.nansen_watch_addresses == ["0xccc", "0xddd"]


def test_min_value_thresholds_read_from_env(monkeypatch):
    monkeypatch.setenv("WHALE_ALERT_MIN_VALUE_USD", "1000000")
    monkeypatch.setenv("BITQUERY_MIN_VALUE_USD", "250000")

    settings = Settings(_env_file=None)

    assert settings.whale_alert_min_value_usd == 1_000_000
    assert settings.bitquery_min_value_usd == 250_000
