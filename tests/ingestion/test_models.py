from datetime import UTC, datetime

from hello_coin.ingestion.models import WhaleEvent


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
