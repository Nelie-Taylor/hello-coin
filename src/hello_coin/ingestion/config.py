from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """App config. Credentials are optional — a missing hyperdash token means
    the ingestion adapter reports itself as not configured and is skipped, and
    the same goes for Telegram, Coinglass, and Anthropic keys; the app never
    fails to start over a missing key."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    exchange_watch_symbols: Annotated[list[str], NoDecode] = ["BTCUSDT"]
    hyperdash_api_token: str | None = None
    hyperdash_watch_coins: Annotated[list[str], NoDecode] = ["LINK", "SOL", "SUI", "NEAR", "HYPE"]
    hyperdash_delta_timeframe: str = "FIFTEEN_MINUTES"
    hyperdash_min_delta_usd: int = 10_000
    hyperdash_min_position_usd: int = 10_000

    technical_timeframe: str = "1h"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    coinglass_api_key: str | None = None
    liquidation_proximity_pct: float = 0.10
    liquidation_poll_interval_seconds: int = 900

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080

    @field_validator(
        "exchange_watch_symbols",
        "hyperdash_watch_coins",
        mode="before",
    )
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
