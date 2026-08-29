import json
from datetime import UTC, datetime

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
async def test_fetch_second_refresh_reports_open_after_silent_baseline():
    wallet = "0x3333333333333333333333333333333333333333"
    graphql = respx.post(HYPERDASH_GRAPHQL_URL)
    graphql.side_effect = [
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": []}}}),
        httpx.Response(
            200,
            json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 80_000}]}}},
        ),
    ]
    respx.post(HYPERLIQUID_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "assetPositions": [
                    {"position": {"coin": "LINK", "szi": "2", "positionValue": "80_000"}}
                ]
            },
        )
    )
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()
    assert adapter.consume_position_changes() == []

    await adapter.fetch()

    changes = adapter.consume_position_changes()
    assert [(change.action, change.event.symbol) for change in changes] == [("open", "LINK")]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_rechecks_prior_wallet_and_reports_confirmed_close():
    wallet = "0x4444444444444444444444444444444444444444"
    graphql = respx.post(HYPERDASH_GRAPHQL_URL)
    graphql.side_effect = [
        httpx.Response(
            200,
            json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 80_000}]}}},
        ),
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": []}}}),
    ]
    state = respx.post(HYPERLIQUID_INFO_URL)
    state.side_effect = [
        httpx.Response(
            200,
            json={
                "assetPositions": [
                    {"position": {"coin": "LINK", "szi": "2", "positionValue": "80_000"}}
                ]
            },
        ),
        httpx.Response(200, json={"assetPositions": []}),
    ]
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()
    await adapter.fetch()

    changes = adapter.consume_position_changes()
    assert [(change.action, change.event.wallet_address) for change in changes] == [("close", wallet)]
    assert state.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_does_not_close_position_when_prior_wallet_recheck_fails():
    wallet = "0x5555555555555555555555555555555555555555"
    graphql = respx.post(HYPERDASH_GRAPHQL_URL)
    graphql.side_effect = [
        httpx.Response(
            200,
            json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 80_000}]}}},
        ),
        httpx.Response(200, json={"data": {"perpDeltas": {"deltas": []}}}),
    ]
    state = respx.post(HYPERLIQUID_INFO_URL)
    state.side_effect = [
        httpx.Response(
            200,
            json={
                "assetPositions": [
                    {"position": {"coin": "LINK", "szi": "2", "positionValue": "80_000"}}
                ]
            },
        ),
        httpx.Response(500),
    ]
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()
    await adapter.fetch()

    assert adapter.consume_position_changes() == []
