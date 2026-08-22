import pytest

from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.okx import OkxAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

ADAPTER_CLASSES = [BinanceAdapter, OkxAdapter, BybitAdapter, BitgetAdapter]


@pytest.mark.network
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_cls", ADAPTER_CLASSES, ids=[c.name for c in ADAPTER_CLASSES])
async def test_fetch_reaches_real_exchange_api(adapter_cls):
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = adapter_cls(settings)

    metrics = await adapter.fetch()

    assert isinstance(metrics, list)
    assert len(metrics) == 1
    assert all(isinstance(metric, WhaleMetric) for metric in metrics)
