import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.hyperdash import (
    HYPERDASH_GRAPHQL_URL,
    HYPERLIQUID_INFO_URL,
    HyperdashAdapter,
    _parse_position,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent


def test_parse_position_normalizes_long_and_leverage():
    event = _parse_position(
        "0xabc",
        {
            "coin": "BTC",
            "szi": "2.5",
            "positionValue": "150000",
            "entryPx": "60000",
            "liquidationPx": "30000",
            "unrealizedPnl": "1250",
            "returnOnEquity": "0.08",
            "leverage": {"type": "cross", "value": 7},
        },
        datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert event is not None
    assert event.event_type == "position"
    assert event.side == "buy"
    assert event.amount == 2.5
    assert event.amount_usd == 150_000
    assert event.raw["entryPx"] == "60000"
    assert event.raw["leverage"] == {"type": "cross", "value": 7}


def test_parse_position_normalizes_short_and_missing_optional_fields():
    event = _parse_position(
        "0xabc",
        {"coin": "ETH", "szi": "-3", "positionValue": "-51000"},
        datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert event is not None
    assert event.side == "sell"
    assert event.amount == 3
    assert event.amount_usd == 51_000
    assert event.raw.get("leverage") is None


def test_parse_position_ignores_zero_size():
    assert _parse_position("0xabc", {"coin": "BTC", "szi": "0", "positionValue": "0"}, datetime.now(UTC)) is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_filters_deltas_and_deduplicates_wallet_state_requests():
    wallet = "0x1111111111111111111111111111111111111111"
    graphql = respx.post(HYPERDASH_GRAPHQL_URL)
    graphql.side_effect = [
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": [
            {"address": wallet, "current": 60_000}, {"address": "0xsmall", "current": 10_000}
        ]}}}),
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": [
            {"address": wallet, "current": -70_000}
        ]}}}),
    ]
    state = respx.post(HYPERLIQUID_INFO_URL).mock(return_value=httpx.Response(200, json={
        "assetPositions": [{"position": {"coin": "LINK", "szi": "2", "positionValue": "80000", "leverage": {"type": "cross", "value": 5}}}]
    }))

    adapter = HyperdashAdapter(Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK", "SOL"]))
    events = await adapter.fetch()

    assert len(events) == 1
    assert state.call_count == 1
    assert json.loads(graphql.calls[0].request.content)["variables"]["market"] == "LINK"
    assert json.loads(graphql.calls[1].request.content)["variables"]["market"] == "SOL"
    assert graphql.calls[0].request.headers["origin"] == "https://hyperdash.com"
    assert graphql.calls[0].request.headers["referer"] == "https://hyperdash.com/"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_isolates_coin_graphql_failure():
    good_wallet = "0x2222222222222222222222222222222222222222"
    route = respx.post(HYPERDASH_GRAPHQL_URL)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": [{"address": good_wallet, "current": 80_000}]}}}),
    ]
    respx.post(HYPERLIQUID_INFO_URL).mock(return_value=httpx.Response(200, json={
        "assetPositions": [{"position": {"coin": "SOL", "szi": "-1", "positionValue": "90000"}}]
    }))

    adapter = HyperdashAdapter(Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK", "SOL"]))
    events = await adapter.fetch()

    assert [event.symbol for event in events] == ["SOL"]
    assert adapter.coin_statuses["LINK"]["state"] == "ERROR"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_emits_enter_alert_when_long_dominance_crosses_75_percent():
    wallet = "0x6666666666666666666666666666666666666666"
    respx.post(HYPERDASH_GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 800_000}]}}}
        )
    )
    respx.post(HYPERLIQUID_INFO_URL).mock(
        return_value=httpx.Response(200, json={
            "assetPositions": [{"position": {"coin": "LINK", "szi": "10", "positionValue": "800000"}}]
        })
    )
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()

    alerts = adapter.consume_skew_alerts()
    assert [(alert.coin, alert.zone, alert.direction) for alert in alerts] == [
        ("LINK", "long_dominant", "enter")
    ]
    assert alerts[0].long_usd == 800_000.0
    assert alerts[0].short_usd == 0.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_emits_exit_alert_when_dominant_wallet_closes_its_position():
    wallet = "0x7777777777777777777777777777777777777777"
    graphql = respx.post(HYPERDASH_GRAPHQL_URL)
    graphql.side_effect = [
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 800_000}]}}}),
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": []}}}),
    ]
    state = respx.post(HYPERLIQUID_INFO_URL)
    state.side_effect = [
        httpx.Response(200, json={
            "assetPositions": [{"position": {"coin": "LINK", "szi": "10", "positionValue": "800000"}}]
        }),
        httpx.Response(200, json={"assetPositions": []}),
    ]
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()
    assert [(alert.zone, alert.direction) for alert in adapter.consume_skew_alerts()] == [
        ("long_dominant", "enter")
    ]

    await adapter.fetch()

    alerts = adapter.consume_skew_alerts()
    assert [(alert.coin, alert.zone, alert.direction) for alert in alerts] == [
        ("LINK", "long_dominant", "exit")
    ]
    assert alerts[0].long_usd == 0.0
    assert alerts[0].short_usd == 0.0


def _adapter(coins: list[str] | None = None) -> HyperdashAdapter:
    return HyperdashAdapter(
        Settings(
            _env_file=None,
            hyperdash_api_token="token",
            hyperdash_watch_coins=coins if coins is not None else ["LINK"],
        )
    )


def _position_event(coin: str, side: str, amount_usd: float) -> WhaleEvent:
    return WhaleEvent(
        source="hyperdash",
        timestamp=datetime(2026, 8, 31, tzinfo=UTC),
        chain_or_exchange="hyperliquid",
        symbol=coin,
        event_type="position",
        side=side,
        amount=1.0,
        amount_usd=amount_usd,
        wallet_address="0xabc",
        dedup_key="k",
        raw={},
    )


def test_update_skew_queues_snapshot_for_every_watched_coin_including_zero_positions():
    adapter = _adapter(coins=["LINK", "SOL"])
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)

    adapter._update_skew({}, now)

    snapshots = adapter.consume_skew_snapshots()
    assert {snapshot.coin for snapshot in snapshots} == {"LINK", "SOL"}
    assert all(snapshot.long_pct == 0.0 and snapshot.short_pct == 0.0 for snapshot in snapshots)
    assert all(snapshot.timestamp == now for snapshot in snapshots)


def test_update_skew_throttles_snapshots_within_five_minutes():
    adapter = _adapter()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    event = _position_event("LINK", "buy", 800_000.0)
    adapter._update_skew({("0xabc", "LINK"): event}, now)
    adapter.consume_skew_snapshots()

    adapter._update_skew({("0xabc", "LINK"): event}, now + timedelta(minutes=4))

    assert adapter.consume_skew_snapshots() == []


def test_update_skew_emits_new_snapshot_after_five_minutes():
    adapter = _adapter()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    event = _position_event("LINK", "buy", 800_000.0)
    adapter._update_skew({("0xabc", "LINK"): event}, now)
    adapter.consume_skew_snapshots()

    later = now + timedelta(minutes=5)
    adapter._update_skew({("0xabc", "LINK"): event}, later)

    snapshots = adapter.consume_skew_snapshots()
    assert [snapshot.coin for snapshot in snapshots] == ["LINK"]
    assert snapshots[0].timestamp == later
    assert snapshots[0].long_pct == 1.0
