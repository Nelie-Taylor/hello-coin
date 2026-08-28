from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Ingestion config. Every adapter's credentials are optional here — a
    missing key means that adapter reports itself as not configured and is
    skipped, not that the app fails to start."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hyperliquid_watch_addresses: Annotated[list[str], NoDecode] = []
    exchange_watch_symbols: Annotated[list[str], NoDecode] = ["BTCUSDT"]
    hyperdash_api_token: str | None = None
    hyperdash_watch_coins: Annotated[list[str], NoDecode] = ["LINK", "SOL", "SUI", "NEAR", "HYPE"]
    hyperdash_delta_timeframe: str = "FIFTEEN_MINUTES"
    hyperdash_min_delta_usd: int = 50_000
    hyperdash_min_position_usd: int = 50_000
    etherscan_api_key: str | None = None
    etherscan_watch_addresses: Annotated[list[str], NoDecode] = []

    debank_access_key: str | None = None
    debank_watch_addresses: Annotated[list[str], NoDecode] = []
    cryptoquant_api_key: str | None = None
    nansen_api_key: str | None = None
    nansen_watch_addresses: Annotated[list[str], NoDecode] = []
    whale_alert_api_key: str | None = None
    whale_alert_min_value_usd: int = 500_000
    bitquery_access_token: str | None = None
    bitquery_min_value_usd: int = 500_000

    technical_timeframe: str = "1h"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    decision_whale_lookback_hours: int = 24

    coinglass_api_key: str | None = None
    liquidation_proximity_pct: float = 0.10
    liquidation_poll_interval_seconds: int = 900

    @field_validator(
        "hyperliquid_watch_addresses",
        "exchange_watch_symbols",
        "hyperdash_watch_coins",
        "etherscan_watch_addresses",
        "debank_watch_addresses",
        "nansen_watch_addresses",
        mode="before",
    )
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
