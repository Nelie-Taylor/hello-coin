# Whale Position Skew Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-wallet open/close Telegram notification with a per-coin LONG/SHORT
dominance alert: notify when one side's tracked whale position value crosses above 75% of the
coin's total (dominant), and notify again when it drops back below 70% (cooling off / possible
exit).

**Architecture:** `HyperdashAdapter.fetch()` already builds a full snapshot of every tracked
wallet's current position per coin (`observed`) on every poll — no new data source or database
query is needed. A new pure module, `position_skew.py`, turns per-coin `(long_usd, short_usd)`
totals into zone transitions with hysteresis (`SkewTracker`). The adapter exposes queued
`SkewAlert`s through `consume_skew_alerts()`, replacing `consume_position_changes()` end to end:
`Adapter` base, `HyperdashAdapter`, `scheduler.poll_once`, and `TelegramNotifier` all switch from
`PositionChange` to `SkewAlert`. The whole open/close-detection mechanism
(`PositionChangeTracker`, `PositionChange`, `position_changes.py`) is deleted, not deprecated —
nothing else depends on it once this lands.

**Tech Stack:** Pure Python (no new dependencies), pytest/pytest-asyncio/respx (existing).

Full design: `docs/superpowers/specs/2026-08-30-whale-position-skew-alerts-design.md`

---

### Task 1: `position_skew.py` — pure skew/hysteresis logic

**Files:**
- Create: `src/hello_coin/ingestion/position_skew.py`
- Test: `tests/ingestion/test_position_skew.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/test_position_skew.py`:

```python
from hello_coin.ingestion.position_skew import SkewAlert, SkewTracker, compute_skew, next_zone


def test_compute_skew_returns_zero_zero_for_zero_total():
    assert compute_skew(0, 0) == (0.0, 0.0)


def test_compute_skew_splits_long_and_short_percentages():
    assert compute_skew(800_000, 200_000) == (0.8, 0.2)


def test_next_zone_enters_long_dominant_above_75_percent():
    assert next_zone("neutral", 0.80, 0.20) == "long_dominant"


def test_next_zone_enters_short_dominant_above_75_percent():
    assert next_zone("neutral", 0.20, 0.80) == "short_dominant"


def test_next_zone_stays_neutral_in_dead_zone():
    assert next_zone("neutral", 0.72, 0.28) == "neutral"


def test_next_zone_stays_long_dominant_within_dead_zone():
    assert next_zone("long_dominant", 0.72, 0.28) == "long_dominant"


def test_next_zone_exits_long_dominant_below_70_percent():
    assert next_zone("long_dominant", 0.65, 0.35) == "neutral"


def test_next_zone_exits_short_dominant_below_70_percent():
    assert next_zone("short_dominant", 0.35, 0.65) == "neutral"


def test_tracker_stays_neutral_with_no_positions_ever_observed():
    tracker = SkewTracker()

    assert tracker.update("LINK", 0, 0) is None


def test_tracker_emits_enter_alert_on_first_crossing():
    tracker = SkewTracker()

    alert = tracker.update("LINK", 800_000, 200_000)

    assert alert == SkewAlert("LINK", "long_dominant", "enter", 800_000, 200_000, 0.8, 0.2)


def test_tracker_stays_silent_while_remaining_in_dominant_zone():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    assert tracker.update("LINK", 780_000, 220_000) is None


def test_tracker_emits_exit_alert_when_dropping_below_70_percent():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    alert = tracker.update("LINK", 650_000, 350_000)

    assert alert == SkewAlert("LINK", "long_dominant", "exit", 650_000, 350_000, 0.65, 0.35)


def test_tracker_emits_exit_alert_when_all_positions_close():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    alert = tracker.update("LINK", 0, 0)

    assert alert == SkewAlert("LINK", "long_dominant", "exit", 0, 0, 0.0, 0.0)


def test_tracker_tracks_each_coin_independently():
    tracker = SkewTracker()

    link_alert = tracker.update("LINK", 800_000, 200_000)
    sol_alert = tracker.update("SOL", 100_000, 900_000)

    assert link_alert.zone == "long_dominant"
    assert sol_alert.zone == "short_dominant"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.position_skew'`

- [ ] **Step 3: Implement the module**

Create `src/hello_coin/ingestion/position_skew.py`:

```python
"""Pure, framework-free LONG/SHORT dominance tracking for whale positions."""

from dataclasses import dataclass
from typing import Literal

SkewZone = Literal["neutral", "long_dominant", "short_dominant"]

DOMINANT_THRESHOLD = 0.75
EXIT_THRESHOLD = 0.70


def compute_skew(long_usd: float, short_usd: float) -> tuple[float, float]:
    total = long_usd + short_usd
    if total <= 0:
        return 0.0, 0.0
    return long_usd / total, short_usd / total


def next_zone(current: SkewZone, long_pct: float, short_pct: float) -> SkewZone:
    if current == "neutral":
        if long_pct > DOMINANT_THRESHOLD:
            return "long_dominant"
        if short_pct > DOMINANT_THRESHOLD:
            return "short_dominant"
        return "neutral"
    if current == "long_dominant":
        return "neutral" if long_pct < EXIT_THRESHOLD else "long_dominant"
    return "neutral" if short_pct < EXIT_THRESHOLD else "short_dominant"


@dataclass(frozen=True)
class SkewAlert:
    coin: str
    zone: SkewZone
    direction: Literal["enter", "exit"]
    long_usd: float
    short_usd: float
    long_pct: float
    short_pct: float


class SkewTracker:
    """Per-coin LONG/SHORT dominance state, with hysteresis between 70% and 75%."""

    def __init__(self) -> None:
        self._zones: dict[str, SkewZone] = {}

    def update(self, coin: str, long_usd: float, short_usd: float) -> SkewAlert | None:
        long_pct, short_pct = compute_skew(long_usd, short_usd)
        current = self._zones.get(coin, "neutral")
        new_zone = next_zone(current, long_pct, short_pct)
        alert: SkewAlert | None = None
        if new_zone != current:
            if new_zone == "neutral":
                alert = SkewAlert(coin, current, "exit", long_usd, short_usd, long_pct, short_pct)
            else:
                alert = SkewAlert(coin, new_zone, "enter", long_usd, short_usd, long_pct, short_pct)
        self._zones[coin] = new_zone
        return alert
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/position_skew.py tests/ingestion/test_position_skew.py
git commit -m "feat: add LONG/SHORT dominance skew tracker"
```

---

### Task 2: `Adapter.consume_skew_alerts()`

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/base.py`
- Test: `tests/ingestion/test_base.py`

- [ ] **Step 1: Write the failing test**

In `tests/ingestion/test_base.py`, change:

```python
def test_consume_position_changes_defaults_to_empty():
    adapter = _AlwaysSucceedsAdapter()

    assert adapter.consume_position_changes() == []
```

to:

```python
def test_consume_skew_alerts_defaults_to_empty():
    adapter = _AlwaysSucceedsAdapter()

    assert adapter.consume_skew_alerts() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: FAIL with `AttributeError: '_AlwaysSucceedsAdapter' object has no attribute
'consume_skew_alerts'`

- [ ] **Step 3: Rename the method on the base class**

In `src/hello_coin/ingestion/adapters/base.py`, change the import:

```python
from hello_coin.ingestion.models import PositionChange, WhaleEvent, WhaleMetric
```

to:

```python
from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
from hello_coin.ingestion.position_skew import SkewAlert
```

Then change:

```python
    def consume_position_changes(self) -> list[PositionChange]:
        """Return newly detected position transitions, if this source has any."""
        return []
```

to:

```python
    def consume_skew_alerts(self) -> list[SkewAlert]:
        """Return newly detected LONG/SHORT dominance transitions, if this source has any."""
        return []
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS (nothing else references the renamed base method yet — `HyperdashAdapter` still
defines its own `consume_position_changes()`, independent of the base class, until Task 3)

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/adapters/base.py tests/ingestion/test_base.py
git commit -m "refactor: rename Adapter.consume_position_changes to consume_skew_alerts"
```

---

### Task 3: Wire skew computation into `HyperdashAdapter`

Replaces `PositionChangeTracker` (open/close diffing) with `SkewTracker` (aggregate dominance),
computed from the same `observed` snapshot `fetch()` already builds every poll.

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/hyperdash.py` (full rewrite)
- Delete: `src/hello_coin/ingestion/position_changes.py`
- Delete: `tests/ingestion/test_position_changes.py`
- Modify: `tests/ingestion/test_hyperdash.py`

- [ ] **Step 1: Write the failing tests**

In `tests/ingestion/test_hyperdash.py`, replace these three tests —
`test_fetch_second_refresh_reports_open_after_silent_baseline`,
`test_fetch_rechecks_prior_wallet_and_reports_confirmed_close`, and
`test_fetch_does_not_close_position_when_prior_wallet_recheck_fails` (everything from
`async def test_fetch_second_refresh_reports_open_after_silent_baseline():` through the end of
the file) — with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v`
Expected: FAIL — `AttributeError: 'HyperdashAdapter' object has no attribute
'consume_skew_alerts'` (the adapter still only defines `consume_position_changes`)

- [ ] **Step 3: Rewrite the adapter**

Replace all of `src/hello_coin/ingestion/adapters/hyperdash.py` with:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.position_skew import SkewAlert, SkewTracker

HYPERDASH_GRAPHQL_URL = "https://api.hyperdash.com/graphql"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERDASH_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://hyperdash.com",
    "Referer": "https://hyperdash.com/",
    "User-Agent": "Mozilla/5.0",
}
GET_PERP_DELTAS_QUERY = (
    "query GetPerpDeltas($market: String!, $timeframe: DeltaTimeframe!) "
    "{ perpDeltas(market: $market, timeframe: $timeframe) "
    "{ market timeframe deltas { address current delta } } }"
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_position(address: str, position: dict[str, Any], timestamp: datetime) -> WhaleEvent | None:
    size = _number(position.get("szi"))
    position_value = _number(position.get("positionValue"))
    coin = position.get("coin")
    if size is None or position_value is None or not coin or size == 0:
        return None
    raw = dict(position)
    return WhaleEvent(
        source="hyperdash",
        timestamp=timestamp,
        chain_or_exchange="hyperliquid",
        symbol=str(coin).upper(),
        event_type="position",
        side="buy" if size > 0 else "sell",
        amount=abs(size),
        amount_usd=abs(position_value),
        wallet_address=address,
        dedup_key=f"position:{address}:{coin}:{size}:{timestamp.isoformat()}",
        raw=raw,
    )


class HyperdashAdapter(Adapter):
    name = "hyperdash"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self.coin_statuses: dict[str, dict[str, str | datetime | None]] = {
            coin.upper(): {"state": "STALE", "detail": "no successful poll", "last_success_at": None}
            for coin in settings.hyperdash_watch_coins
        }
        self._skew_tracker = SkewTracker()
        self._active_wallets_by_coin: dict[str, set[str]] = {
            coin.upper(): set() for coin in settings.hyperdash_watch_coins
        }
        self._pending_skew_alerts: list[SkewAlert] = []

    def is_configured(self) -> bool:
        return bool(self._settings.hyperdash_api_token and self._settings.hyperdash_watch_coins)

    async def fetch(self) -> list[WhaleEvent]:
        if not self.is_configured():
            for status in self.coin_statuses.values():
                status.update(state="NOT CONFIGURED", detail="HYPERDASH_API_TOKEN is not set")
            return []
        now = datetime.now(tz=UTC)
        events: list[WhaleEvent] = []
        addresses_by_coin: dict[str, set[str]] = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for configured_coin in self._settings.hyperdash_watch_coins:
                coin = configured_coin.upper()
                try:
                    response = await client.post(
                        HYPERDASH_GRAPHQL_URL,
                        headers={
                            **HYPERDASH_HEADERS,
                            "Authorization": f"Bearer {self._settings.hyperdash_api_token}",
                        },
                        json={
                            "operationName": "GetPerpDeltas",
                            "variables": {
                                "market": coin,
                                "timeframe": self._settings.hyperdash_delta_timeframe,
                            },
                            "query": GET_PERP_DELTAS_QUERY,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    deltas = payload["data"]["perpDeltas"]["deltas"]
                    addresses = {
                        str(row["address"])
                        for row in deltas
                        if _number(row.get("current")) is not None
                        and abs(float(row["current"])) >= self._settings.hyperdash_min_delta_usd
                        and row.get("address")
                    }
                    addresses_by_coin[coin] = addresses
                    self.coin_statuses[coin] = {
                        "state": "LIVE",
                        "detail": f"{len(addresses)} qualifying wallet(s)",
                        "last_success_at": now,
                    }
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    self.coin_statuses[coin] = {
                        "state": "ERROR",
                        "detail": str(error),
                        "last_success_at": self.coin_statuses.get(coin, {}).get("last_success_at"),
                    }
            coins_by_address: dict[str, set[str]] = {}
            for coin, candidate_addresses in addresses_by_coin.items():
                addresses = candidate_addresses | self._active_wallets_by_coin[coin]
                for address in addresses:
                    coins_by_address.setdefault(address, set()).add(coin)

            observed: dict[tuple[str, str], WhaleEvent] = {}
            confirmed: set[tuple[str, str]] = set()
            for address, coins in coins_by_address.items():
                try:
                    response = await client.post(
                        HYPERLIQUID_INFO_URL,
                        json={"type": "clearinghouseState", "user": address},
                    )
                    response.raise_for_status()
                    positions = response.json().get("assetPositions", [])
                    positions_by_coin = {
                        str(asset_position.get("position", {}).get("coin", "")).upper():
                        asset_position.get("position", {})
                        for asset_position in positions
                    }
                    for coin in coins:
                        key = (address, coin)
                        if address in self._active_wallets_by_coin[coin]:
                            confirmed.add(key)
                        event = _parse_position(address, positions_by_coin.get(coin, {}), now)
                        is_tracked = address in self._active_wallets_by_coin[coin]
                        if event and (is_tracked or event.amount_usd >= self._settings.hyperdash_min_position_usd):
                            observed[key] = event
                            if event.amount_usd >= self._settings.hyperdash_min_position_usd:
                                events.append(event)
                except (httpx.HTTPError, AttributeError, TypeError, ValueError) as error:
                    for coin in coins:
                        self.coin_statuses[coin] = {
                            "state": "ERROR",
                            "detail": f"Hyperliquid {address[:10]}: {error}",
                            "last_success_at": self.coin_statuses[coin].get("last_success_at"),
                        }

            self._update_skew(observed)
            for address, coin in confirmed:
                if (address, coin) not in observed:
                    self._active_wallets_by_coin[coin].discard(address)
            for address, coin in observed:
                self._active_wallets_by_coin[coin].add(address)
        return events

    def _update_skew(self, observed: dict[tuple[str, str], WhaleEvent]) -> None:
        totals: dict[str, tuple[float, float]] = {}
        for (_, coin), event in observed.items():
            long_usd, short_usd = totals.get(coin, (0.0, 0.0))
            amount_usd = event.amount_usd or 0.0
            if event.side == "buy":
                long_usd += amount_usd
            else:
                short_usd += amount_usd
            totals[coin] = (long_usd, short_usd)
        for configured_coin in self._settings.hyperdash_watch_coins:
            coin = configured_coin.upper()
            long_usd, short_usd = totals.get(coin, (0.0, 0.0))
            alert = self._skew_tracker.update(coin, long_usd, short_usd)
            if alert is not None:
                self._pending_skew_alerts.append(alert)

    def consume_skew_alerts(self) -> list[SkewAlert]:
        alerts = self._pending_skew_alerts
        self._pending_skew_alerts = []
        return alerts
```

- [ ] **Step 4: Run the Hyperdash tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v`
Expected: PASS (every test in the file, including the two new ones and the pre-existing delta
filtering / error isolation / position parsing tests, which are unaffected)

- [ ] **Step 5: Delete the now-unused open/close tracker**

```bash
git rm src/hello_coin/ingestion/position_changes.py tests/ingestion/test_position_changes.py
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS. (`notifications.py`, `test_notifications.py`, and `test_scheduler.py` still
reference `PositionChange` at this point — that's fine, `models.py` hasn't changed yet, they're
fixed in Tasks 4 and 5.)

- [ ] **Step 7: Commit**

```bash
git add src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py
git commit -m "feat: compute LONG/SHORT dominance in HyperdashAdapter instead of open/close diffing"
```

---

### Task 4: `TelegramNotifier` sends skew alerts (Vietnamese)

**Files:**
- Modify: `src/hello_coin/ingestion/notifications.py` (full rewrite)
- Test: `tests/ingestion/test_notifications.py` (full rewrite)

- [ ] **Step 1: Write the failing tests**

Replace all of `tests/ingestion/test_notifications.py` with:

```python
import json

import httpx
import pytest
import respx

from hello_coin.ingestion.notifications import TelegramNotifier, format_skew_notification
from hello_coin.ingestion.position_skew import SkewAlert


def _alert(
    zone: str = "long_dominant",
    direction: str = "enter",
    long_usd: float = 820_000.0,
    short_usd: float = 180_000.0,
) -> SkewAlert:
    total = long_usd + short_usd
    return SkewAlert(
        coin="LINK",
        zone=zone,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        long_usd=long_usd,
        short_usd=short_usd,
        long_pct=long_usd / total,
        short_pct=short_usd / total,
    )


def test_enter_long_dominant_notification():
    title, body = format_skew_notification(_alert("long_dominant", "enter", 820_000, 180_000))

    assert title == "LINK: LONG áp đảo (82%)"
    assert body == "Long $820,000 vs Short $180,000 (tổng $1,000,000)"


def test_enter_short_dominant_notification():
    title, body = format_skew_notification(_alert("short_dominant", "enter", 180_000, 820_000))

    assert title == "LINK: SHORT áp đảo (82%)"
    assert body == "Short $820,000 vs Long $180,000 (tổng $1,000,000)"


def test_exit_long_dominant_notification():
    title, body = format_skew_notification(_alert("long_dominant", "exit", 680_000, 320_000))

    assert title == "LINK: LONG hạ nhiệt (68%)"
    assert body == "Long $680,000 vs Short $320,000 — có thể đang thoát lệnh"


def test_exit_short_dominant_notification():
    title, body = format_skew_notification(_alert("short_dominant", "exit", 320_000, 680_000))

    assert title == "LINK: SHORT hạ nhiệt (68%)"
    assert body == "Short $680,000 vs Long $320,000 — có thể đang thoát lệnh"


@pytest.mark.asyncio
@respx.mock
async def test_notify_posts_title_and_body_to_telegram_api():
    route = respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_alert())

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "chat456"
    assert "LINK: LONG áp đảo" in payload["text"]


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_bot_token():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier(None, "chat456", client=client)
        await notifier.notify(_alert())


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_chat_id():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", None, client=client)
        await notifier.notify(_alert())


@pytest.mark.asyncio
@respx.mock
async def test_notify_logs_delivery_failure_without_raising(caplog):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_alert())

    assert "failed to send Telegram notification" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_notifications.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_skew_notification'`

- [ ] **Step 3: Rewrite the notifications module**

Replace all of `src/hello_coin/ingestion/notifications.py` with:

```python
import logging
from typing import Protocol

import httpx

from hello_coin.ingestion.position_skew import SkewAlert

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationSink(Protocol):
    async def notify(self, alert: SkewAlert) -> None: ...


def format_skew_notification(alert: SkewAlert) -> tuple[str, str]:
    if alert.zone == "long_dominant":
        side_label, own_pct = "LONG", alert.long_pct
        comparison = f"Long ${alert.long_usd:,.0f} vs Short ${alert.short_usd:,.0f}"
    else:
        side_label, own_pct = "SHORT", alert.short_pct
        comparison = f"Short ${alert.short_usd:,.0f} vs Long ${alert.long_usd:,.0f}"
    percent = f"{own_pct:.0%}"
    if alert.direction == "enter":
        title = f"{alert.coin}: {side_label} áp đảo ({percent})"
        total = alert.long_usd + alert.short_usd
        body = f"{comparison} (tổng ${total:,.0f})"
    else:
        title = f"{alert.coin}: {side_label} hạ nhiệt ({percent})"
        body = f"{comparison} — có thể đang thoát lệnh"
    return title, body


class TelegramNotifier:
    """Deliver whale LONG/SHORT dominance alerts via the Telegram Bot API.

    A missing bot token or chat ID is treated as "not configured" — `notify()` is a
    silent no-op, matching every other optional credential in this codebase.
    """

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def notify(self, alert: SkewAlert) -> None:
        if not self._bot_token or not self._chat_id:
            return
        title, body = format_skew_notification(alert)
        try:
            response = await self._client.post(
                TELEGRAM_API_URL.format(token=self._bot_token),
                json={"chat_id": self._chat_id, "text": f"{title}\n{body}"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("failed to send Telegram notification")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_notifications.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS (`test_scheduler.py` still references `PositionChange` — fixed in Task 5)

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/notifications.py tests/ingestion/test_notifications.py
git commit -m "feat: send Vietnamese LONG/SHORT dominance alerts via Telegram"
```

---

### Task 5: Wire the scheduler to skew alerts and delete `PositionChange`

**Files:**
- Modify: `src/hello_coin/ingestion/scheduler.py`
- Modify: `tests/ingestion/test_scheduler.py`
- Modify: `src/hello_coin/ingestion/models.py`

- [ ] **Step 1: Update the scheduler test fixtures and assertions**

In `tests/ingestion/test_scheduler.py`, change the import:

```python
from hello_coin.ingestion.models import PositionChange, WhaleEvent
```

to:

```python
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.position_skew import SkewAlert
```

Change the fake adapter:

```python
class _PositionChangeAdapter(_FixedResultAdapter):
    def __init__(self, result, changes: list[PositionChange]) -> None:
        super().__init__(result)
        self._changes = changes

    def consume_position_changes(self) -> list[PositionChange]:
        changes = self._changes
        self._changes = []
        return changes
```

to:

```python
class _SkewAlertAdapter(_FixedResultAdapter):
    def __init__(self, result, alerts: list[SkewAlert]) -> None:
        super().__init__(result)
        self._alerts = alerts

    def consume_skew_alerts(self) -> list[SkewAlert]:
        alerts = self._alerts
        self._alerts = []
        return alerts
```

Change:

```python
@pytest.mark.asyncio
async def test_poll_once_notifies_changes_after_persisting_events():
    storage = WhaleStorage(":memory:")
    event = _event("new")
    adapter = _PositionChangeAdapter([event], [PositionChange("open", event)])

    class _Notifier:
        def __init__(self) -> None:
            self.count_when_notified = 0
            self.changes: list[PositionChange] = []

        async def notify(self, change: PositionChange) -> None:
            self.count_when_notified = storage.count_events()
            self.changes.append(change)

    notifier = _Notifier()

    inserted = await poll_once(adapter, storage, notifier)

    assert inserted == 1
    assert notifier.count_when_notified == 1
    assert notifier.changes == [PositionChange("open", event)]


@pytest.mark.asyncio
async def test_poll_once_logs_notifier_failure_and_returns_insert_count(caplog):
    storage = WhaleStorage(":memory:")
    event = _event("new")
    adapter = _PositionChangeAdapter([event], [PositionChange("open", event)])

    class _FailingNotifier:
        async def notify(self, change: PositionChange) -> None:
            raise RuntimeError("toast unavailable")

    inserted = await poll_once(adapter, storage, _FailingNotifier())

    assert inserted == 1
    assert "failed to deliver whale position notification" in caplog.text
```

to:

```python
@pytest.mark.asyncio
async def test_poll_once_notifies_changes_after_persisting_events():
    storage = WhaleStorage(":memory:")
    event = _event("new")
    alert = SkewAlert("BTC", "long_dominant", "enter", 800_000.0, 200_000.0, 0.8, 0.2)
    adapter = _SkewAlertAdapter([event], [alert])

    class _Notifier:
        def __init__(self) -> None:
            self.count_when_notified = 0
            self.alerts: list[SkewAlert] = []

        async def notify(self, alert: SkewAlert) -> None:
            self.count_when_notified = storage.count_events()
            self.alerts.append(alert)

    notifier = _Notifier()

    inserted = await poll_once(adapter, storage, notifier)

    assert inserted == 1
    assert notifier.count_when_notified == 1
    assert notifier.alerts == [alert]


@pytest.mark.asyncio
async def test_poll_once_logs_notifier_failure_and_returns_insert_count(caplog):
    storage = WhaleStorage(":memory:")
    event = _event("new")
    alert = SkewAlert("BTC", "long_dominant", "enter", 800_000.0, 200_000.0, 0.8, 0.2)
    adapter = _SkewAlertAdapter([event], [alert])

    class _FailingNotifier:
        async def notify(self, alert: SkewAlert) -> None:
            raise RuntimeError("telegram unavailable")

    inserted = await poll_once(adapter, storage, _FailingNotifier())

    assert inserted == 1
    assert "failed to deliver whale position notification" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: FAIL — `_SkewAlertAdapter` defines `consume_skew_alerts()`, but `poll_once` still
calls `adapter.consume_position_changes()`, which `_SkewAlertAdapter` (and its base
`_FixedResultAdapter`, which no longer inherits a `consume_position_changes` default from
`Adapter`) doesn't have: `AttributeError`.

- [ ] **Step 3: Update the scheduler**

In `src/hello_coin/ingestion/scheduler.py`, change:

```python
    if notifier is not None:
        for change in adapter.consume_position_changes():
            try:
                await notifier.notify(change)
            except Exception:
                logger.exception("failed to deliver whale position notification")
```

to:

```python
    if notifier is not None:
        for alert in adapter.consume_skew_alerts():
            try:
                await notifier.notify(alert)
            except Exception:
                logger.exception("failed to deliver whale position notification")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Delete `PositionChange` — nothing imports it anymore**

Run:

```bash
grep -rn "PositionChange" src tests --include=*.py
```

Expected: no output (confirms every remaining consumer has already been migrated).

In `src/hello_coin/ingestion/models.py`, change:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class WhaleEvent:
    """A single discrete whale action tied to one wallet (transfer, fill, position)."""

    source: str
    timestamp: datetime
    chain_or_exchange: str
    symbol: str
    event_type: str  # "transfer" | "fill" | "position"
    side: str | None
    amount: float
    amount_usd: float | None
    wallet_address: str | None
    dedup_key: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionChange:
    """A confirmed open or close transition for one whale position."""

    action: Literal["open", "close"]
    event: WhaleEvent


@dataclass(frozen=True)
class WhaleMetric:
```

to:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WhaleEvent:
    """A single discrete whale action tied to one wallet (transfer, fill, position)."""

    source: str
    timestamp: datetime
    chain_or_exchange: str
    symbol: str
    event_type: str  # "transfer" | "fill" | "position"
    side: str | None
    amount: float
    amount_usd: float | None
    wallet_address: str | None
    dedup_key: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WhaleMetric:
```

(`Literal` is dropped from the `typing` import since `PositionChange` was its only user in this
file; the rest of `WhaleMetric` below is unchanged.)

- [ ] **Step 6: Run the full suite and lint**

Run: `uv run pytest`
Expected: PASS, zero failures.

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/hello_coin/ingestion/scheduler.py tests/ingestion/test_scheduler.py \
  src/hello_coin/ingestion/models.py
git commit -m "feat: wire scheduler to skew alerts and remove PositionChange"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Telegram alert description**

In `README.md`, change:

```markdown
To get whale position open/close alerts on Telegram instead of watching the dashboard, set
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (see `.env.example`). Without both set, no
alerts are sent — everything else keeps working.
```

to:

```markdown
To get whale LONG/SHORT dominance alerts on Telegram instead of watching the dashboard, set
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (see `.env.example`). For each Hyperdash
watch coin, an alert fires when tracked whales' LONG or SHORT position value crosses above 75%
of the coin's total (that side is now dominant) and again when it drops back below 70% (cooling
off — a possible sign of exiting). Without both env vars set, no alerts are sent — everything
else keeps working.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: describe LONG/SHORT dominance alerts instead of open/close alerts"
```

---

### Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: PASS, zero failures.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 3: Confirm no leftover references to the removed open/close mechanism**

Run: `grep -rn "PositionChange\|position_changes\|consume_position_changes" src tests --include=*.py`
Expected: no matches.
