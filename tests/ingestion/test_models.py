from datetime import UTC, datetime

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric


def test_whale_event_holds_fields():
    event = WhaleEvent(
        source="hyperliquid",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        chain_or_exchange="hyperliquid",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.5,
        amount_usd=90000.0,
        wallet_address="0xabc",
        dedup_key="hash:tid",
        raw={"coin": "BTC"},
    )

    assert event.symbol == "BTC"
    assert event.amount_usd == 90000.0
    assert event.raw == {"coin": "BTC"}


def test_whale_metric_holds_fields():
    metric = WhaleMetric(
        source="binance",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        symbol="BTCUSDT",
        metric_name="top_trader_long_short_ratio",
        value=1.8,
        dedup_key="binance:BTCUSDT:2026-08-22T00:00:00",
        raw={"longShortRatio": "1.8"},
    )

    assert metric.value == 1.8
    assert metric.metric_name == "top_trader_long_short_ratio"
