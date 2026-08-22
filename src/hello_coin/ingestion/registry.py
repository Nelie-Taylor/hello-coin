import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.etherscan import ETHERSCAN_CHAINS, EtherscanAdapter
from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.adapters.okx import OkxAdapter
from hello_coin.ingestion.config import Settings

logger = logging.getLogger(__name__)


def build_adapters(settings: Settings) -> list[Adapter]:
    """Return every adapter that reports itself as configured, logging a
    warning for each one that's skipped. Add new adapters to `candidates`
    here as they're implemented."""

    candidates: list[Adapter] = [
        HyperliquidAdapter(settings),
        BinanceAdapter(settings),
        OkxAdapter(settings),
        BybitAdapter(settings),
        BitgetAdapter(settings),
        *(EtherscanAdapter(settings, chain_key=chain_key) for chain_key in ETHERSCAN_CHAINS),
    ]

    configured: list[Adapter] = []
    for adapter in candidates:
        if adapter.is_configured():
            configured.append(adapter)
        else:
            logger.warning("%s: not configured, skipping", adapter.name)
    return configured
