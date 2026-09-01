from hello_coin.ingestion.config import Settings


def test_exchange_watch_symbols_defaults_to_btcusdt(monkeypatch):
    monkeypatch.delenv("EXCHANGE_WATCH_SYMBOLS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT"]


def test_exchange_watch_symbols_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("EXCHANGE_WATCH_SYMBOLS", "BTCUSDT, ETHUSDT ,SOLUSDT")

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_technical_timeframe_defaults_to_1h(monkeypatch):
    monkeypatch.delenv("TECHNICAL_TIMEFRAME", raising=False)

    settings = Settings(_env_file=None)

    assert settings.technical_timeframe == "1h"


def test_technical_timeframe_reads_from_env(monkeypatch):
    monkeypatch.setenv("TECHNICAL_TIMEFRAME", "4h")

    settings = Settings(_env_file=None)

    assert settings.technical_timeframe == "4h"


def test_decision_settings_default(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-sonnet-5"


def test_decision_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.anthropic_model == "claude-opus-5"


def test_liquidation_settings_default(monkeypatch):
    for var in (
        "COINGLASS_API_KEY",
        "LIQUIDATION_PROXIMITY_PCT",
        "LIQUIDATION_POLL_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.coinglass_api_key is None
    assert settings.liquidation_proximity_pct == 0.10
    assert settings.liquidation_poll_interval_seconds == 900


def test_liquidation_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "cg-test-key")
    monkeypatch.setenv("LIQUIDATION_PROXIMITY_PCT", "0.05")
    monkeypatch.setenv("LIQUIDATION_POLL_INTERVAL_SECONDS", "300")

    settings = Settings(_env_file=None)

    assert settings.coinglass_api_key == "cg-test-key"
    assert settings.liquidation_proximity_pct == 0.05
    assert settings.liquidation_poll_interval_seconds == 300


def test_hyperdash_settings_defaults(monkeypatch):
    for var in (
        "HYPERDASH_API_TOKEN",
        "HYPERDASH_WATCH_COINS",
        "HYPERDASH_DELTA_TIMEFRAME",
        "HYPERDASH_MIN_DELTA_USD",
        "HYPERDASH_MIN_POSITION_USD",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.hyperdash_api_token is None
    assert settings.hyperdash_watch_coins == ["LINK", "SOL", "SUI", "NEAR", "HYPE"]
    assert settings.hyperdash_delta_timeframe == "FIFTEEN_MINUTES"
    assert settings.hyperdash_min_delta_usd == 50_000
    assert settings.hyperdash_min_position_usd == 50_000


def test_hyperdash_settings_parse_environment(monkeypatch):
    monkeypatch.setenv("HYPERDASH_API_TOKEN", "test-token")
    monkeypatch.setenv("HYPERDASH_WATCH_COINS", "BTC, ETH ,SOL")
    monkeypatch.setenv("HYPERDASH_DELTA_TIMEFRAME", "ONE_HOUR")
    monkeypatch.setenv("HYPERDASH_MIN_DELTA_USD", "100000")
    monkeypatch.setenv("HYPERDASH_MIN_POSITION_USD", "250000")

    settings = Settings(_env_file=None)

    assert settings.hyperdash_api_token == "test-token"
    assert settings.hyperdash_watch_coins == ["BTC", "ETH", "SOL"]
    assert settings.hyperdash_delta_timeframe == "ONE_HOUR"
    assert settings.hyperdash_min_delta_usd == 100_000
    assert settings.hyperdash_min_position_usd == 250_000


def test_telegram_and_dashboard_settings_default(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_HOST", "DASHBOARD_PORT"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token is None
    assert settings.telegram_chat_id is None
    assert settings.dashboard_host == "0.0.0.0"
    assert settings.dashboard_port == 8080


def test_telegram_and_dashboard_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("DASHBOARD_PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token == "bot-token"
    assert settings.telegram_chat_id == "12345"
    assert settings.dashboard_host == "127.0.0.1"
    assert settings.dashboard_port == 9000
