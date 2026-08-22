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
    etherscan_api_key: str | None = None
    etherscan_watch_addresses: Annotated[list[str], NoDecode] = []

    @field_validator(
        "hyperliquid_watch_addresses",
        "exchange_watch_symbols",
        "etherscan_watch_addresses",
        mode="before",
    )
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
