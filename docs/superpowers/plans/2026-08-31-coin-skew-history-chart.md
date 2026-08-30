# Coin LONG/SHORT Skew History Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a LONG/SHORT dominance snapshot per watched coin every 5 minutes, retain 30 days
of it, and chart it inside each coin's dashboard panel.

**Architecture:** `HyperdashAdapter` already computes per-coin `(long_usd, short_usd)` totals on
every poll for its existing Telegram dominance alerts; it now also queues a throttled (5-minute)
snapshot the same way it queues alerts. `scheduler.poll_once()` drains and persists those
snapshots into a new `coin_skew_snapshots` table in `data/whale.db`, pruning anything older than
30 days on each write. `DashboardService` reads the last 30 days per coin into
`CoinPositionTable.skew_history`, and the dashboard template renders it into a `<canvas>` per coin
panel using a vendored Chart.js, re-drawn on every htmx panel refresh.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 (via Starlette), SQLite, pytest / pytest-asyncio /
respx, vanilla JS + vendored Chart.js (no new Python dependency).

Spec: `docs/superpowers/specs/2026-08-31-coin-skew-history-chart-design.md`

---

### Task 1: `SkewSnapshot` dataclass and snapshot interval constant

**Files:**
- Modify: `src/hello_coin/ingestion/position_skew.py`
- Test: `tests/ingestion/test_position_skew.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/test_position_skew.py`:

```python
from datetime import UTC, datetime

from hello_coin.ingestion.position_skew import (
    SNAPSHOT_INTERVAL_SECONDS,
    SkewAlert,
    SkewSnapshot,
    SkewTracker,
    compute_skew,
    next_zone,
)


def test_snapshot_interval_is_five_minutes():
    assert SNAPSHOT_INTERVAL_SECONDS == 300


def test_skew_snapshot_holds_coin_timestamp_and_percentages():
    snapshot = SkewSnapshot(
        coin="LINK",
        timestamp=datetime(2026, 8, 31, tzinfo=UTC),
        long_usd=800_000.0,
        short_usd=200_000.0,
        long_pct=0.8,
        short_pct=0.2,
    )

    assert snapshot.coin == "LINK"
    assert snapshot.long_pct == 0.8
    assert snapshot.short_pct == 0.2
```

(This replaces the existing `from hello_coin.ingestion.position_skew import SkewAlert,
SkewTracker, compute_skew, next_zone` import line at the top of the file — extend it with
`SNAPSHOT_INTERVAL_SECONDS` and `SkewSnapshot` rather than adding a second import line.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkewSnapshot' from 'hello_coin.ingestion.position_skew'`

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/position_skew.py`, add `datetime` to the imports at the top:

```python
"""Pure, framework-free LONG/SHORT dominance tracking for whale positions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SkewZone = Literal["neutral", "long_dominant", "short_dominant"]

DOMINANT_THRESHOLD = 0.75
EXIT_THRESHOLD = 0.70
SNAPSHOT_INTERVAL_SECONDS = 300
```

Then add the new dataclass right after the existing `SkewAlert` dataclass (before `class
SkewTracker`):

```python
@dataclass(frozen=True)
class SkewSnapshot:
    coin: str
    timestamp: datetime
    long_usd: float
    short_usd: float
    long_pct: float
    short_pct: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/position_skew.py tests/ingestion/test_position_skew.py
git commit -m "feat: add SkewSnapshot and 5-minute snapshot interval constant"
```

---

### Task 2: `coin_skew_snapshots` storage

**Files:**
- Modify: `src/hello_coin/ingestion/storage.py`
- Test: `tests/ingestion/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_storage.py` (add `timedelta` to the existing `from datetime
import UTC, datetime` line, and add the `SkewSnapshot` import):

```python
from hello_coin.ingestion.position_skew import SkewSnapshot


def _skew_snapshot(coin: str, timestamp: datetime, long_pct: float = 0.8) -> SkewSnapshot:
    return SkewSnapshot(
        coin=coin,
        timestamp=timestamp,
        long_usd=long_pct * 1_000_000,
        short_usd=(1 - long_pct) * 1_000_000,
        long_pct=long_pct,
        short_pct=1 - long_pct,
    )


def test_insert_skew_snapshots_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")
    snapshot = _skew_snapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC))

    inserted_first = storage.insert_skew_snapshots([snapshot])
    inserted_second = storage.insert_skew_snapshots([snapshot])

    assert inserted_first == 1
    assert inserted_second == 0


def test_insert_skew_snapshots_prunes_rows_older_than_30_days_relative_to_batch():
    storage = WhaleStorage(":memory:")
    storage.insert_skew_snapshots([_skew_snapshot("LINK", datetime(2026, 1, 1, tzinfo=UTC))])

    newer = datetime(2026, 8, 31, tzinfo=UTC)
    storage.insert_skew_snapshots([_skew_snapshot("LINK", newer)])

    remaining = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [row["timestamp"] for row in remaining] == [newer.isoformat()]


def test_insert_skew_snapshots_keeps_rows_within_30_days_of_batch():
    storage = WhaleStorage(":memory:")
    within_window = datetime(2026, 8, 5, tzinfo=UTC)  # 26 days before the batch below
    storage.insert_skew_snapshots([_skew_snapshot("LINK", within_window)])

    storage.insert_skew_snapshots([_skew_snapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC))])

    remaining = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert len(remaining) == 2


def test_recent_skew_history_filters_by_coin_case_insensitive_since_ordered_ascending():
    storage = WhaleStorage(":memory:")
    storage.insert_skew_snapshots([
        _skew_snapshot("LINK", datetime(2026, 8, 31, 0, 0, tzinfo=UTC), long_pct=0.6),
        _skew_snapshot("LINK", datetime(2026, 8, 31, 0, 5, tzinfo=UTC), long_pct=0.7),
        _skew_snapshot("SOL", datetime(2026, 8, 31, 0, 5, tzinfo=UTC), long_pct=0.9),
    ])

    rows = storage.recent_skew_history("link", since=datetime(2026, 8, 31, tzinfo=UTC))

    assert [row["long_pct"] for row in rows] == [0.6, 0.7]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_storage.py -v`
Expected: FAIL — `AttributeError: 'WhaleStorage' object has no attribute 'insert_skew_snapshots'`

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/storage.py`, change the imports at the top from:

```python
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
```

to:

```python
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
from hello_coin.ingestion.position_skew import SkewSnapshot
```

Add a new schema constant after `_METRICS_SCHEMA`:

```python
_SKEW_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS coin_skew_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    long_usd REAL NOT NULL,
    short_usd REAL NOT NULL,
    long_pct REAL NOT NULL,
    short_pct REAL NOT NULL,
    UNIQUE(coin, timestamp)
)
"""

_SKEW_SNAPSHOT_COLUMNS = ("coin", "timestamp", "long_usd", "short_usd", "long_pct", "short_pct")
```

In `WhaleStorage.__init__`, add the new table alongside the existing two:

```python
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_EVENTS_SCHEMA)
        self._conn.execute(_METRICS_SCHEMA)
        self._conn.execute(_SKEW_SNAPSHOTS_SCHEMA)
        self._conn.commit()
```

Add the two new methods at the end of the class (after `recent_metrics`):

```python
    def insert_skew_snapshots(self, snapshots: list[SkewSnapshot]) -> int:
        inserted = 0
        for snapshot in snapshots:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO coin_skew_snapshots
                    (coin, timestamp, long_usd, short_usd, long_pct, short_pct)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.coin,
                    snapshot.timestamp.isoformat(),
                    snapshot.long_usd,
                    snapshot.short_usd,
                    snapshot.long_pct,
                    snapshot.short_pct,
                ),
            )
            inserted += cursor.rowcount
        if snapshots:
            # Deriving the cutoff from the batch's own latest timestamp (rather than
            # datetime.now()) keeps this deterministic and testable, and pruning naturally
            # happens on every adapter poll cycle that has fresh data.
            cutoff = max(snapshot.timestamp for snapshot in snapshots) - timedelta(days=30)
            self._conn.execute(
                "DELETE FROM coin_skew_snapshots WHERE timestamp < ?", (cutoff.isoformat(),)
            )
        self._conn.commit()
        return inserted

    def recent_skew_history(self, coin: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT coin, timestamp, long_usd, short_usd, long_pct, short_pct
            FROM coin_skew_snapshots
            WHERE coin = ? COLLATE NOCASE AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (coin, since.isoformat()),
        ).fetchall()
        return [dict(zip(_SKEW_SNAPSHOT_COLUMNS, row, strict=True)) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_storage.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/storage.py tests/ingestion/test_storage.py
git commit -m "feat: persist and query coin skew history snapshots"
```

---

### Task 3: `Adapter.consume_skew_snapshots()` default

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/base.py`
- Test: `tests/ingestion/test_base.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/test_base.py`:

```python
def test_consume_skew_snapshots_defaults_to_empty():
    adapter = _AlwaysSucceedsAdapter()

    assert adapter.consume_skew_snapshots() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: FAIL — `AttributeError: '_AlwaysSucceedsAdapter' object has no attribute
'consume_skew_snapshots'`

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/adapters/base.py`, change the import line:

```python
from hello_coin.ingestion.position_skew import SkewAlert
```

to:

```python
from hello_coin.ingestion.position_skew import SkewAlert, SkewSnapshot
```

Add the new method after `consume_skew_alerts`:

```python
    def consume_skew_snapshots(self) -> list[SkewSnapshot]:
        """Return newly sampled LONG/SHORT dominance snapshots, if this source has any."""
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/base.py tests/ingestion/test_base.py
git commit -m "feat: add default Adapter.consume_skew_snapshots()"
```

---

### Task 4: Throttled snapshot queuing in `HyperdashAdapter`

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/hyperdash.py`
- Test: `tests/ingestion/test_hyperdash.py`

`_update_skew()` is tested directly with controlled `now` values (rather than through `fetch()` +
`respx` + real wall-clock time) because the 5-minute throttle needs precise, repeatable timestamps
that a live `datetime.now(tz=UTC)` call can't give a test.

- [ ] **Step 1: Write the failing tests**

Add these imports to the top of `tests/ingestion/test_hyperdash.py` (alongside the existing
`from datetime import UTC, datetime` line, extend it to `from datetime import UTC, datetime,
timedelta`, and add a `WhaleEvent` import):

```python
from hello_coin.ingestion.models import WhaleEvent
```

Append to the end of the file:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v -k update_skew`
Expected: FAIL — `TypeError: _update_skew() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/adapters/hyperdash.py`, change the import line:

```python
from hello_coin.ingestion.position_skew import SkewAlert, SkewTracker
```

to:

```python
from hello_coin.ingestion.position_skew import (
    SNAPSHOT_INTERVAL_SECONDS,
    SkewAlert,
    SkewSnapshot,
    SkewTracker,
    compute_skew,
)
```

In `HyperdashAdapter.__init__`, add two new instance attributes after `self._pending_skew_alerts
= []`:

```python
        self._pending_skew_alerts: list[SkewAlert] = []
        self._last_skew_snapshot_at: dict[str, datetime] = {}
        self._pending_skew_snapshots: list[SkewSnapshot] = []
```

In `fetch()`, change the call `self._update_skew(observed)` to `self._update_skew(observed, now)`.

Replace `_update_skew` with:

```python
    def _update_skew(
        self, observed: dict[tuple[str, str], WhaleEvent], now: datetime
    ) -> None:
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
            last_snapshot_at = self._last_skew_snapshot_at.get(coin)
            due = (
                last_snapshot_at is None
                or (now - last_snapshot_at).total_seconds() >= SNAPSHOT_INTERVAL_SECONDS
            )
            if due:
                long_pct, short_pct = compute_skew(long_usd, short_usd)
                self._pending_skew_snapshots.append(
                    SkewSnapshot(coin, now, long_usd, short_usd, long_pct, short_pct)
                )
                self._last_skew_snapshot_at[coin] = now
```

Add `consume_skew_snapshots` after `consume_skew_alerts`:

```python
    def consume_skew_snapshots(self) -> list[SkewSnapshot]:
        snapshots = self._pending_skew_snapshots
        self._pending_skew_snapshots = []
        return snapshots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v`
Expected: PASS (all tests, old and new — the existing `fetch()`-level tests are unaffected since
`_update_skew`'s alert-producing logic is unchanged, only extended)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py
git commit -m "feat: queue throttled skew snapshots in HyperdashAdapter"
```

---

### Task 5: Persist snapshots from `scheduler.poll_once`

**Files:**
- Modify: `src/hello_coin/ingestion/scheduler.py`
- Test: `tests/ingestion/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

In `tests/ingestion/test_scheduler.py`, add `timedelta` to the existing `from datetime import
UTC, datetime` line, and add a `SkewSnapshot` import alongside the existing `SkewAlert` import:

```python
from hello_coin.ingestion.position_skew import SkewAlert, SkewSnapshot
```

Append a new fake adapter class after `_SkewAlertAdapter`:

```python
class _SkewSnapshotAdapter(_FixedResultAdapter):
    def __init__(self, result, snapshots: list[SkewSnapshot]) -> None:
        super().__init__(result)
        self._snapshots = snapshots

    def consume_skew_snapshots(self) -> list[SkewSnapshot]:
        snapshots = self._snapshots
        self._snapshots = []
        return snapshots
```

Append a new test:

```python
@pytest.mark.asyncio
async def test_poll_once_persists_skew_snapshots():
    storage = WhaleStorage(":memory:")
    snapshot = SkewSnapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC), 800_000.0, 200_000.0, 0.8, 0.2)
    adapter = _SkewSnapshotAdapter([], [snapshot])

    await poll_once(adapter, storage)

    history = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [row["long_pct"] for row in history] == [0.8]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v -k persists_skew_snapshots`
Expected: FAIL — `history` is `[]` (nothing persisted yet)

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/scheduler.py`, add the persistence call in `poll_once` right after
the existing insert branch and before the notifier block:

```python
async def poll_once(
    adapter: Adapter,
    storage: WhaleStorage,
    notifier: NotificationSink | None = None,
) -> int:
    result = await adapter.safe_fetch()
    if not result:
        inserted = 0
    elif isinstance(result[0], WhaleEvent):
        inserted = storage.insert_events(result)
    else:
        inserted = storage.insert_metrics(result)

    storage.insert_skew_snapshots(adapter.consume_skew_snapshots())

    if notifier is not None:
        for alert in adapter.consume_skew_alerts():
            try:
                await notifier.notify(alert)
            except Exception:
                logger.exception("failed to deliver whale position notification")
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/scheduler.py tests/ingestion/test_scheduler.py
git commit -m "feat: persist coin skew snapshots on every adapter poll"
```

---

### Task 6: `CoinPositionTable.skew_history` and `DashboardService` wiring

**Files:**
- Modify: `src/hello_coin/dashboard/models.py`
- Modify: `src/hello_coin/dashboard/service.py`
- Test: `tests/dashboard/test_service.py`

- [ ] **Step 1: Write the failing test**

In `tests/dashboard/test_service.py`, add an import alongside the existing ones:

```python
from hello_coin.ingestion.position_skew import SkewSnapshot
```

Append a new test:

```python
def test_load_snapshot_includes_skew_history_per_coin():
    whale_storage = WhaleStorage(":memory:")
    service = DashboardService(
        whale_storage,
        TechnicalStorage(":memory:"),
        timeframe="1h",
        lookback_hours=24,
        hyperdash_watch_coins=["LINK"],
    )
    whale_storage.insert_skew_snapshots([
        SkewSnapshot("LINK", NOW - timedelta(minutes=5), 800_000.0, 200_000.0, 0.8, 0.2),
        SkewSnapshot("LINK", NOW, 700_000.0, 300_000.0, 0.7, 0.3),
    ])

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert [row["long_pct"] for row in snapshot.coin_positions[0].skew_history] == [0.8, 0.7]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dashboard/test_service.py -v -k skew_history`
Expected: FAIL — `AttributeError: 'CoinPositionTable' object has no attribute 'skew_history'`

- [ ] **Step 3: Implement**

In `src/hello_coin/dashboard/models.py`, add a fourth field with a default to `CoinPositionTable`:

```python
@dataclass(frozen=True)
class CoinPositionTable:
    coin: str
    rows: tuple[dict[str, Any], ...]
    status: SourceStatus
    skew_history: tuple[dict[str, Any], ...] = ()
```

In `src/hello_coin/dashboard/service.py`, update `_load_coin_positions` to fetch and attach each
coin's history:

```python
    def _load_coin_positions(
        self, sources: Sequence[Adapter], now: datetime
    ) -> tuple[CoinPositionTable, ...]:
        if not self._hyperdash_watch_coins:
            return ()
        hyperdash = next((source for source in sources if source.name == "hyperdash"), None)
        freshness = self._position_freshness_seconds
        if freshness is None:
            freshness = min((hyperdash.poll_interval_seconds * 2 if hyperdash else 120), 300)
        since = now - timedelta(seconds=freshness)
        # 30 days matches WhaleStorage.insert_skew_snapshots's own pruning window.
        skew_since = now - timedelta(days=30)
        tables: list[CoinPositionTable] = []
        for coin in self._hyperdash_watch_coins:
            rows: list[dict] = []
            for row in self._whale_storage.recent_events(coin, since):
                if row["source"] != "hyperdash" or row["event_type"] != "position":
                    continue
                try:
                    row["raw"] = json.loads(row["raw"])
                except (TypeError, json.JSONDecodeError):
                    row["raw"] = {}
                rows.append(row)
            rows.sort(key=lambda row: row["amount_usd"] or 0, reverse=True)
            status = self._coin_status(coin, hyperdash, now, bool(rows))
            skew_history = tuple(self._whale_storage.recent_skew_history(coin, skew_since))
            tables.append(
                CoinPositionTable(coin=coin, rows=tuple(rows), status=status, skew_history=skew_history)
            )
        return tuple(tables)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_service.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/dashboard/models.py src/hello_coin/dashboard/service.py tests/dashboard/test_service.py
git commit -m "feat: load per-coin skew history into DashboardService snapshots"
```

---

### Task 7: Render the skew chart canvas in the dashboard template

**Files:**
- Modify: `src/hello_coin/dashboard/web.py`
- Modify: `src/hello_coin/dashboard/templates/_panels.html`
- Modify: `src/hello_coin/dashboard/static/dashboard.css`
- Test: `tests/dashboard/test_web.py`

- [ ] **Step 1: Write the failing test**

In `tests/dashboard/test_web.py`, update `_CoinDashboardService.load_snapshot`'s `LINK`
`CoinPositionTable` construction to add a `skew_history`:

```python
class _CoinDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
            coin_positions=(
                CoinPositionTable(
                    "LINK",
                    ({
                        "wallet_address": "0x1234567890abcdef", "side": "buy", "amount": 2.0,
                        "amount_usd": 80_000.0, "timestamp": now.isoformat(),
                        "raw": {"leverage": {"type": "cross", "value": 7}, "entryPx": "10",
                                "liquidationPx": "5", "unrealizedPnl": "100"},
                    },),
                    SourceStatus("hyperdash", "LIVE", now, "current position(s)"),
                    skew_history=({
                        "coin": "LINK", "timestamp": now.isoformat(), "long_usd": 800_000.0,
                        "short_usd": 200_000.0, "long_pct": 0.8, "short_pct": 0.2,
                    },),
                ),
                CoinPositionTable("SOL", (), SourceStatus("hyperdash", "STALE", now, "no fresh positions")),
                CoinPositionTable("SUI", (), SourceStatus("hyperdash", "ERROR", now, "request failed")),
                CoinPositionTable("NEAR", (), SourceStatus("hyperdash", "NOT CONFIGURED", None, "token missing")),
            ),
        )
```

Append a new test:

```python
def test_panels_renders_skew_chart_canvas_with_history_data():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_CoinDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert 'id="coin-link-skew-chart"' in response.text
    assert 'class="skew-chart"' in response.text
    assert "0.8" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_web.py -v -k skew_chart`
Expected: FAIL — `jinja2.exceptions.TemplateAssertionError: No filter named 'tojson'.` (or the
canvas assertions fail once the filter exists but the template doesn't render it yet)

- [ ] **Step 3: Implement**

In `src/hello_coin/dashboard/web.py`, add `import json` to the top imports (alongside the
existing `import asyncio`, `import contextlib`, `import logging`), and register the filter after
`templates.env.globals.update(...)`:

```python
import asyncio
import contextlib
import json
import logging
```

```python
templates.env.globals.update(
    format_number=formatting.format_number,
    format_wallet=formatting.format_wallet,
    format_age=formatting.format_age,
    format_direction=formatting.format_direction,
    is_recent_event=formatting.is_recent_event,
    format_event_leverage=formatting.format_event_leverage,
    format_position_leverage=formatting.format_position_leverage,
    position_side_label=formatting.position_side_label,
    coin_panel_id=formatting.coin_panel_id,
    side_class=formatting.side_class,
    coin_skew=formatting.coin_skew,
)
templates.env.filters["tojson"] = json.dumps
```

In `src/hello_coin/dashboard/templates/_panels.html`, add a `<canvas>` right after the `<h2>`
block inside the coin panel loop:

```html
{% for table in snapshot.coin_positions %}
{% set skew_label, skew_class, skew_entry_avg = coin_skew(table.rows) %}
<div id="{{ coin_panel_id(table.coin) }}" class="panel coin-panel">
  <h2>
    {{ table.coin }} &middot; {{ table.status.state }}
    {%- if skew_label %} &middot; <span class="{{ skew_class }}">{{ skew_label }}</span>{% endif %}
    {%- if skew_entry_avg %} &middot; Entry avg {{ skew_entry_avg }}{% endif %}
  </h2>
  <canvas id="{{ coin_panel_id(table.coin) }}-skew-chart" class="skew-chart"
          data-skew='{{ table.skew_history | tojson }}'></canvas>
  <table>
```

(The rest of `_panels.html` is unchanged — this only inserts the `<canvas>` line between the
existing `</h2>` and `<table>` lines.)

In `src/hello_coin/dashboard/static/dashboard.css`, add a new rule after the `.coin-panel th,
.coin-panel td { ... }` block:

```css
.skew-chart {
  width: 100%;
  max-height: 160px;
  margin-bottom: 0.75rem;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_web.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/dashboard/web.py src/hello_coin/dashboard/templates/_panels.html src/hello_coin/dashboard/static/dashboard.css tests/dashboard/test_web.py
git commit -m "feat: render skew history canvas in each coin panel"
```

---

### Task 8: Vendor Chart.js and draw the chart in the browser

**Files:**
- Create: `src/hello_coin/dashboard/static/chart.min.js` (vendored, downloaded — not hand-written)
- Create: `src/hello_coin/dashboard/static/skew-charts.js`
- Modify: `src/hello_coin/dashboard/templates/page.html`

This task has no Python test — `chart.min.js` is a third-party binary-ish asset and
`skew-charts.js` is browser JS with no test runner in this repo (per `CLAUDE.md`, JS/UI changes
are verified by running the app and checking it in a browser, not by a Python test). Verification
is a file-shape check plus a manual browser check in Step 4.

- [ ] **Step 1: Vendor Chart.js**

Download the Chart.js v4.4.4 UMD build, matching the project's existing convention of vendoring
JS assets locally (see `static/htmx.min.js`) instead of pulling from a CDN at request time:

```bash
curl -fsSL -o src/hello_coin/dashboard/static/chart.min.js \
  https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js
```

Verify the download succeeded and looks like Chart.js:

```bash
wc -c src/hello_coin/dashboard/static/chart.min.js
head -c 80 src/hello_coin/dashboard/static/chart.min.js
```

Expected: file size over 150000 bytes; the first bytes contain `Chart.js` (it's a minified UMD
bundle, so the exact banner text may be `/*!\n * Chart.js v4.4.4\n * https://www.chartjs.org` or
similarly on the very first line).

- [ ] **Step 2: Write `skew-charts.js`**

Create `src/hello_coin/dashboard/static/skew-charts.js`:

```javascript
(function () {
  var charts = {};

  function renderSkewCharts() {
    var canvases = document.querySelectorAll("canvas.skew-chart");
    canvases.forEach(function (canvas) {
      var existing = charts[canvas.id];
      if (existing) {
        existing.destroy();
        delete charts[canvas.id];
      }
      var history;
      try {
        history = JSON.parse(canvas.dataset.skew || "[]");
      } catch (error) {
        history = [];
      }
      if (!history.length) {
        return;
      }
      charts[canvas.id] = new Chart(canvas, {
        type: "line",
        data: {
          labels: history.map(function (row) { return row.timestamp; }),
          datasets: [
            {
              label: "LONG %",
              data: history.map(function (row) { return row.long_pct * 100; }),
              borderColor: "#4ade80",
              backgroundColor: "#4ade80",
              pointRadius: 0,
              borderWidth: 1.5,
            },
            {
              label: "SHORT %",
              data: history.map(function (row) { return row.short_pct * 100; }),
              borderColor: "#ff5c5c",
              backgroundColor: "#ff5c5c",
              pointRadius: 0,
              borderWidth: 1.5,
            },
          ],
        },
        options: {
          animation: false,
          scales: {
            x: { display: false },
            y: {
              min: 0,
              max: 100,
              ticks: { callback: function (value) { return value + "%"; } },
            },
          },
          plugins: { legend: { labels: { boxWidth: 10 } } },
        },
      });
    });
  }

  renderSkewCharts();

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "panels") {
      renderSkewCharts();
    }
  });
})();
```

(`renderSkewCharts()` is called once immediately because this script tag sits at the bottom of
`<body>`, after the coin panels have already been parsed — same reasoning as `dashboard.js`'s own
top-level `render()` call. It's then re-run on every htmx panel swap, mirroring how
`dashboard.js` already listens for `htmx:afterSwap` on `#panels` to reset its refresh countdown.
Destroying the previous chart instance before creating a new one avoids leaking Chart.js's
internal listeners on the canvas element that gets discarded by htmx's `innerHTML` swap.)

- [ ] **Step 3: Wire up the new `<script>` tags**

In `src/hello_coin/dashboard/templates/page.html`, add `chart.min.js` to `<head>` right after
`htmx.min.js`:

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hello Coin Dashboard</title>
  <link rel="stylesheet" href="/static/dashboard.css">
  <script src="/static/htmx.min.js"></script>
  <script src="/static/chart.min.js"></script>
</head>
```

And add `skew-charts.js` right after `dashboard.js` at the bottom of `<body>`:

```html
  <script src="/static/dashboard.js"></script>
  <script src="/static/skew-charts.js"></script>
</body>
```

- [ ] **Step 4: Verify in the browser**

Rebuild and restart the Docker container so the running dashboard reflects these changes (per
this project's review workflow — the project owner reviews via the running dashboard, not the
code):

```bash
docker compose up -d --build
```

Then open `http://localhost:8080` and confirm:
- Every coin panel that has `HYPERDASH_WATCH_COINS` configured shows a chart under its heading.
- The chart has no visible data yet on a fresh deploy (no history accumulated) — that's expected;
  a green LONG % line and red SHORT % line should start appearing after ~5 minutes of the
  ingestion service running.
- The page doesn't show any JS console errors (`Chart is not defined`, JSON parse errors, etc.).
- Waiting for one htmx auto-refresh cycle (see `#refresh-status` countdown) doesn't break the
  chart or duplicate it.

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/dashboard/static/chart.min.js src/hello_coin/dashboard/static/skew-charts.js src/hello_coin/dashboard/templates/page.html
git commit -m "feat: chart per-coin skew history with vendored Chart.js"
```

---

### Task 9: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass, no failures or errors.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check .`
Expected: no lint errors. Fix anything reported (most likely line-length on the wrapped
`CoinPositionTable(coin=..., skew_history=...)` call from Task 6 — wrap it across multiple lines
if `ruff` flags it) and re-run until clean.

- [ ] **Step 3: Confirm the dashboard is rebuilt and running**

If Task 8's Step 4 wasn't the most recent Docker rebuild (e.g. lint fixes changed Python files
afterward), rebuild again:

```bash
docker compose up -d --build
```

Confirm `http://localhost:8080` loads without errors and every coin panel renders its skew chart
canvas.
