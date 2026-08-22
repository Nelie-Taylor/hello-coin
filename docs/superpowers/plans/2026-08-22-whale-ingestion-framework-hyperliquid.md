# Whale Ingestion Framework + Hyperliquid Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the whale-data-ingestion framework (normalized data models, adapter base class,
SQLite storage, async scheduler, CLI) and one fully working adapter — Hyperliquid — so
`uv run hello-coin ingest run` actually polls real whale positions and stores them.

**Architecture:** Adapter pattern + async poller, per
`docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md`. Each data source is an
isolated `Adapter` subclass exposing `fetch()`; a scheduler runs each configured adapter on its
own interval and writes normalized `WhaleEvent`/`WhaleMetric` rows to SQLite. Hyperliquid tracks
a configured watchlist of wallet addresses via its public, unauthenticated `userFillsByTime`
endpoint (no official public leaderboard API exists, so watchlist addresses are supplied by the
user rather than auto-discovered).

**Tech Stack:** Python 3.12, `httpx` (async HTTP), `pydantic-settings` (config), stdlib
`sqlite3` (storage), stdlib `asyncio` (scheduling), `pytest` + `pytest-asyncio` + `respx` (tests).

---

### Task 1: Dependencies and package scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `src/hello_coin/ingestion/__init__.py`
- Create: `tests/ingestion/` (directory, no `__init__.py` needed)

- [ ] **Step 1: Add runtime and dev dependencies**

Run:
```bash
uv add httpx pydantic-settings
uv add --dev pytest-asyncio respx
```

- [ ] **Step 2: Configure pytest-asyncio**

Edit `pyproject.toml`, add after the `[tool.ruff]` section:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "-m 'not network'"
markers = [
    "network: hits a real external API; excluded by default, run with `-m network`",
]
```

- [ ] **Step 3: Create the ingestion package**

Create `src/hello_coin/ingestion/__init__.py` (empty file).

Create the `tests/ingestion/` directory (it will hold this plan's test files).

- [ ] **Step 4: Verify the project still installs and tests still run**

Run: `uv run pytest -q`
Expected: `1 passed` (the existing `tests/test_main.py` test — nothing else exists yet).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/hello_coin/ingestion/__init__.py
git commit -m "Add ingestion package scaffolding and async test deps"
```

---

### Task 2: Whale data models

**Files:**
- Create: `src/hello_coin/ingestion/models.py`
- Test: `tests/ingestion/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_models.py`:

```python
from datetime import datetime, timezone

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric


def test_whale_event_holds_fields():
    event = WhaleEvent(
        source="hyperliquid",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
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
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        metric_name="top_trader_long_short_ratio",
        value=1.8,
        dedup_key="binance:BTCUSDT:2026-08-22T00:00:00",
        raw={"longShortRatio": "1.8"},
    )

    assert metric.value == 1.8
    assert metric.metric_name == "top_trader_long_short_ratio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.models'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/models.py`:

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
    """An aggregate whale-related indicator over time, not tied to one wallet."""

    source: str
    timestamp: datetime
    symbol: str
    metric_name: str
    value: float
    dedup_key: str
    raw: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_models.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/models.py tests/ingestion/test_models.py
git commit -m "Add WhaleEvent and WhaleMetric data models"
```

---

### Task 3: Adapter base class

**Files:**
- Create: `src/hello_coin/ingestion/adapters/__init__.py`
- Create: `src/hello_coin/ingestion/adapters/base.py`
- Test: `tests/ingestion/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_base.py`:

```python
import pytest

from hello_coin.ingestion.adapters.base import Adapter


class _AlwaysSucceedsAdapter(Adapter):
    name = "always_succeeds"
    poll_interval_seconds = 1

    async def fetch(self):
        return []


class _CountingFailingAdapter(Adapter):
    name = "counting_failing"
    poll_interval_seconds = 1
    max_consecutive_failures = 3

    def __init__(self):
        super().__init__()
        self.fetch_calls = 0

    async def fetch(self):
        self.fetch_calls += 1
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_safe_fetch_returns_result_on_success():
    adapter = _AlwaysSucceedsAdapter()

    result = await adapter.safe_fetch()

    assert result == []
    assert adapter.disabled is False


@pytest.mark.asyncio
async def test_safe_fetch_disables_after_max_consecutive_failures():
    adapter = _CountingFailingAdapter()

    for _ in range(3):
        result = await adapter.safe_fetch()
        assert result == []

    assert adapter.disabled is True
    assert adapter.fetch_calls == 3

    await adapter.safe_fetch()
    assert adapter.fetch_calls == 3  # fetch() is not called again once disabled


def test_is_configured_defaults_to_true():
    adapter = _AlwaysSucceedsAdapter()
    assert adapter.is_configured() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/__init__.py` (empty file).

Create `src/hello_coin/ingestion/adapters/base.py`:

```python
import logging
from abc import ABC, abstractmethod

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric

logger = logging.getLogger(__name__)


class Adapter(ABC):
    """Base class for a single whale data source.

    Subclasses implement `fetch()` only. Scheduling, storage, and disabling a
    persistently-failing source are handled here so every adapter behaves the
    same way under errors.
    """

    name: str
    poll_interval_seconds: int
    max_consecutive_failures: int = 5

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._disabled = False

    def is_configured(self) -> bool:
        return True

    @property
    def disabled(self) -> bool:
        return self._disabled

    @abstractmethod
    async def fetch(self) -> list[WhaleEvent] | list[WhaleMetric]:
        raise NotImplementedError

    async def safe_fetch(self) -> list[WhaleEvent] | list[WhaleMetric]:
        if self._disabled:
            return []
        try:
            result = await self.fetch()
        except Exception:
            logger.exception("%s: fetch failed", self.name)
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.max_consecutive_failures:
                self._disabled = True
                logger.error(
                    "%s: disabled after %d consecutive failures",
                    self.name,
                    self._consecutive_failures,
                )
            return []
        self._consecutive_failures = 0
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_base.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/__init__.py src/hello_coin/ingestion/adapters/base.py tests/ingestion/test_base.py
git commit -m "Add Adapter base class with failure-disable behavior"
```

---

### Task 4: Settings and .env handling

**Files:**
- Create: `src/hello_coin/ingestion/config.py`
- Modify: `.gitignore`
- Create: `.env.example`
- Test: `tests/ingestion/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_config.py`:

```python
from hello_coin.ingestion.config import Settings


def test_defaults_to_empty_watch_list(monkeypatch):
    monkeypatch.delenv("HYPERLIQUID_WATCH_ADDRESSES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == []


def test_parses_comma_separated_addresses(monkeypatch):
    monkeypatch.setenv("HYPERLIQUID_WATCH_ADDRESSES", "0xaaa, 0xbbb ,0xccc")

    settings = Settings(_env_file=None)

    assert settings.hyperliquid_watch_addresses == ["0xaaa", "0xbbb", "0xccc"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.config'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/config.py`:

```python
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ingestion config. Every adapter's credentials are optional here — a
    missing key means that adapter reports itself as not configured and is
    skipped, not that the app fails to start."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hyperliquid_watch_addresses: list[str] = []

    @field_validator("hyperliquid_watch_addresses", mode="before")
    @classmethod
    def _split_addresses(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
```

Edit `.gitignore`, append:

```
# Local secrets and data
.env
data/
```

Create `.env.example`:

```
# Comma-separated Hyperliquid wallet addresses to watch (no API key needed).
HYPERLIQUID_WATCH_ADDRESSES=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/config.py .gitignore .env.example tests/ingestion/test_config.py
git commit -m "Add ingestion Settings with per-adapter optional config"
```

---

### Task 5: SQLite storage

**Files:**
- Create: `src/hello_coin/ingestion/storage.py`
- Test: `tests/ingestion/test_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_storage.py`:

```python
from datetime import datetime, timezone

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
from hello_coin.ingestion.storage import WhaleStorage


def _event(dedup_key: str) -> WhaleEvent:
    return WhaleEvent(
        source="hyperliquid",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        chain_or_exchange="hyperliquid",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.0,
        amount_usd=60000.0,
        wallet_address="0xabc",
        dedup_key=dedup_key,
        raw={},
    )


def test_insert_events_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")

    inserted_first = storage.insert_events([_event("a"), _event("b")])
    inserted_second = storage.insert_events([_event("a"), _event("c")])

    assert inserted_first == 2
    assert inserted_second == 1
    assert storage.count_events() == 3
    assert storage.count_events(source="hyperliquid") == 3
    assert storage.count_events(source="other") == 0


def test_insert_metrics_returns_count_and_dedupes():
    storage = WhaleStorage(":memory:")
    metric = WhaleMetric(
        source="binance",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        metric_name="oi",
        value=1.0,
        dedup_key="m1",
        raw={},
    )

    inserted_first = storage.insert_metrics([metric])
    inserted_second = storage.insert_metrics([metric])

    assert inserted_first == 1
    assert inserted_second == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.storage'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/storage.py`:

```python
import json
import sqlite3
from pathlib import Path

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric

_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    chain_or_exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    side TEXT,
    amount REAL NOT NULL,
    amount_usd REAL,
    wallet_address TEXT,
    dedup_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(source, dedup_key)
)
"""

_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    dedup_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(source, dedup_key)
)
"""


class WhaleStorage:
    """SQLite-backed storage for normalized whale data. No business logic —
    just insert (deduped) and basic reads for later consumers."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_EVENTS_SCHEMA)
        self._conn.execute(_METRICS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_events(self, events: list[WhaleEvent]) -> int:
        inserted = 0
        for event in events:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO whale_events
                    (source, timestamp, chain_or_exchange, symbol, event_type, side,
                     amount, amount_usd, wallet_address, dedup_key, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    event.timestamp.isoformat(),
                    event.chain_or_exchange,
                    event.symbol,
                    event.event_type,
                    event.side,
                    event.amount,
                    event.amount_usd,
                    event.wallet_address,
                    event.dedup_key,
                    json.dumps(event.raw),
                ),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def insert_metrics(self, metrics: list[WhaleMetric]) -> int:
        inserted = 0
        for metric in metrics:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO whale_metrics
                    (source, timestamp, symbol, metric_name, value, dedup_key, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric.source,
                    metric.timestamp.isoformat(),
                    metric.symbol,
                    metric.metric_name,
                    metric.value,
                    metric.dedup_key,
                    json.dumps(metric.raw),
                ),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def count_events(self, source: str | None = None) -> int:
        if source is None:
            row = self._conn.execute("SELECT COUNT(*) FROM whale_events").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM whale_events WHERE source = ?", (source,)
            ).fetchone()
        return int(row[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_storage.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/storage.py tests/ingestion/test_storage.py
git commit -m "Add SQLite-backed WhaleStorage with dedup on insert"
```

---

### Task 6: Hyperliquid adapter

**Files:**
- Create: `src/hello_coin/ingestion/adapters/hyperliquid.py`
- Test: `tests/ingestion/test_hyperliquid.py`

Hyperliquid is a fully on-chain perp DEX: every wallet's fills are public via the unauthenticated
`POST https://api.hyperliquid.xyz/info` endpoint with `{"type": "userFillsByTime", "user": ...,
"startTime": ...}`. There is no official public "leaderboard" JSON endpoint, so this adapter
tracks a watchlist of addresses supplied via `HYPERLIQUID_WATCH_ADDRESSES` rather than
discovering whales automatically.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_hyperliquid.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.hyperliquid import HYPERLIQUID_INFO_URL, HyperliquidAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0x1111111111111111111111111111111111111111"

FILL_RESPONSE = [
    {
        "coin": "BTC",
        "px": "60000.0",
        "sz": "2.5",
        "side": "B",
        "time": 1750000000000,
        "startPosition": "0.0",
        "dir": "Open Long",
        "closedPnl": "0.0",
        "hash": "0xabc123",
        "oid": 42,
        "crossed": True,
        "fee": "1.2",
        "tid": 999,
        "feeToken": "USDC",
    }
]


def test_is_configured_true_when_addresses_set():
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_addresses():
    settings = Settings(hyperliquid_watch_addresses=[])
    adapter = HyperliquidAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_fill_into_whale_event():
    respx.post(HYPERLIQUID_INFO_URL).mock(return_value=httpx.Response(200, json=FILL_RESPONSE))
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "hyperliquid"
    assert event.symbol == "BTC"
    assert event.side == "buy"
    assert event.amount == 2.5
    assert event.amount_usd == 150000.0
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xabc123:999"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_advances_start_time_on_second_call():
    route = respx.post(HYPERLIQUID_INFO_URL).mock(
        return_value=httpx.Response(200, json=FILL_RESPONSE)
    )
    settings = Settings(hyperliquid_watch_addresses=[ADDRESS])
    adapter = HyperliquidAdapter(settings)

    await adapter.fetch()
    await adapter.fetch()

    second_request_body = route.calls[1].request.content
    assert b'"startTime": 1750000000001' in second_request_body or b'"startTime":1750000000001' in second_request_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_hyperliquid.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.hyperliquid'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/hyperliquid.py`:

```python
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
ONE_HOUR_MS = 3_600_000


def _parse_fill(address: str, fill: dict[str, Any]) -> WhaleEvent:
    side = "buy" if fill["side"] == "B" else "sell"
    price = float(fill["px"])
    size = float(fill["sz"])
    return WhaleEvent(
        source="hyperliquid",
        timestamp=datetime.fromtimestamp(fill["time"] / 1000, tz=timezone.utc),
        chain_or_exchange="hyperliquid",
        symbol=fill["coin"],
        event_type="fill",
        side=side,
        amount=size,
        amount_usd=price * size,
        wallet_address=address,
        dedup_key=f"{fill['hash']}:{fill['tid']}",
        raw=fill,
    )


class HyperliquidAdapter(Adapter):
    """Tracks fills for a configured watchlist of Hyperliquid wallet addresses.

    No API key needed — Hyperliquid's info endpoint is public and unauthenticated.
    """

    name = "hyperliquid"
    poll_interval_seconds = 20

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen_ms: dict[str, int] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.hyperliquid_watch_addresses)

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.hyperliquid_watch_addresses:
                start_time = self._last_seen_ms.get(
                    address, int(time.time() * 1000) - ONE_HOUR_MS
                )
                response = await client.post(
                    HYPERLIQUID_INFO_URL,
                    json={"type": "userFillsByTime", "user": address, "startTime": start_time},
                )
                response.raise_for_status()
                fills = response.json()
                for fill in fills:
                    events.append(_parse_fill(address, fill))
                if fills:
                    self._last_seen_ms[address] = max(fill["time"] for fill in fills) + 1
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_hyperliquid.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/hyperliquid.py tests/ingestion/test_hyperliquid.py
git commit -m "Add Hyperliquid whale-fills adapter"
```

---

### Task 7: Adapter registry

**Files:**
- Create: `src/hello_coin/ingestion/registry.py`
- Test: `tests/ingestion/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_registry.py`:

```python
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters


def test_build_adapters_includes_configured_hyperliquid():
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid"]


def test_build_adapters_skips_unconfigured_hyperliquid(caplog):
    settings = Settings(hyperliquid_watch_addresses=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert adapters == []
    assert "hyperliquid" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.registry'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/registry.py`:

```python
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.config import Settings

logger = logging.getLogger(__name__)


def build_adapters(settings: Settings) -> list[Adapter]:
    """Return every adapter that reports itself as configured, logging a
    warning for each one that's skipped. Add new adapters to `candidates`
    here as they're implemented."""

    candidates: list[Adapter] = [HyperliquidAdapter(settings)]

    configured: list[Adapter] = []
    for adapter in candidates:
        if adapter.is_configured():
            configured.append(adapter)
        else:
            logger.warning("%s: not configured, skipping", adapter.name)
    return configured
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/registry.py tests/ingestion/test_registry.py
git commit -m "Add adapter registry that skips unconfigured sources"
```

---

### Task 8: Async scheduler

**Files:**
- Create: `src/hello_coin/ingestion/scheduler.py`
- Test: `tests/ingestion/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_scheduler.py`:

```python
import asyncio
from datetime import datetime, timezone

import pytest

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.scheduler import poll_once, run_adapter_loop
from hello_coin.ingestion.storage import WhaleStorage


def _event(dedup_key: str) -> WhaleEvent:
    return WhaleEvent(
        source="fake",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        chain_or_exchange="fake",
        symbol="BTC",
        event_type="fill",
        side="buy",
        amount=1.0,
        amount_usd=1.0,
        wallet_address="0xabc",
        dedup_key=dedup_key,
        raw={},
    )


class _FixedResultAdapter(Adapter):
    name = "fake"
    poll_interval_seconds = 0

    def __init__(self, result):
        super().__init__()
        self._result = result

    async def fetch(self):
        return self._result


@pytest.mark.asyncio
async def test_poll_once_inserts_events_and_returns_count():
    storage = WhaleStorage(":memory:")
    adapter = _FixedResultAdapter([_event("a"), _event("b")])

    inserted = await poll_once(adapter, storage)

    assert inserted == 2
    assert storage.count_events() == 2


@pytest.mark.asyncio
async def test_poll_once_returns_zero_for_empty_result():
    storage = WhaleStorage(":memory:")
    adapter = _FixedResultAdapter([])

    inserted = await poll_once(adapter, storage)

    assert inserted == 0


@pytest.mark.asyncio
async def test_run_adapter_loop_stops_when_event_set_during_fetch():
    storage = WhaleStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    class _OneShotAdapter(Adapter):
        name = "one_shot"
        poll_interval_seconds = 0

        async def fetch(self):
            nonlocal call_count
            call_count += 1
            stop_event.set()
            return []

    await run_adapter_loop(_OneShotAdapter(), storage, stop_event)

    assert call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.scheduler'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/scheduler.py`:

```python
import asyncio
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.models import WhaleEvent
from hello_coin.ingestion.storage import WhaleStorage

logger = logging.getLogger(__name__)


async def poll_once(adapter: Adapter, storage: WhaleStorage) -> int:
    result = await adapter.safe_fetch()
    if not result:
        return 0
    if isinstance(result[0], WhaleEvent):
        return storage.insert_events(result)
    return storage.insert_metrics(result)


async def run_adapter_loop(
    adapter: Adapter, storage: WhaleStorage, stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(adapter, storage)
        logger.info("%s: inserted %d new row(s)", adapter.name, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=adapter.poll_interval_seconds)
        except asyncio.TimeoutError:
            pass


async def run_forever(adapters: list[Adapter], storage: WhaleStorage) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(run_adapter_loop(adapter, storage, stop_event) for adapter in adapters)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/scheduler.py tests/ingestion/test_scheduler.py
git commit -m "Add async scheduler that polls each adapter on its own interval"
```

---

### Task 9: CLI and entry point

**Files:**
- Create: `src/hello_coin/cli.py`
- Modify: `src/hello_coin/__init__.py`
- Test: `tests/test_cli.py`
- Delete: `tests/test_main.py` (tests the placeholder greeting this task removes)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from hello_coin.cli import build_parser


def test_ingest_run_parses():
    parser = build_parser()

    args = parser.parse_args(["ingest", "run"])

    assert args.command == "ingest"
    assert args.ingest_command == "run"


def test_ingest_test_parses_source():
    parser = build_parser()

    args = parser.parse_args(["ingest", "test", "hyperliquid"])

    assert args.command == "ingest"
    assert args.ingest_command == "test"
    assert args.source == "hyperliquid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.cli'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/cli.py`:

```python
import argparse
import asyncio
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever
from hello_coin.ingestion.storage import WhaleStorage

DEFAULT_DB_PATH = "data/whale.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-coin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Whale data ingestion commands")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)
    ingest_subparsers.add_parser("run", help="Run the ingestion service continuously")
    test_parser = ingest_subparsers.add_parser(
        "test", help="Fetch once from a single adapter and print the result"
    )
    test_parser.add_argument("source", help="Adapter name, e.g. hyperliquid")

    return parser


async def _run_ingest() -> None:
    settings = Settings()
    adapters = build_adapters(settings)
    storage = WhaleStorage(DEFAULT_DB_PATH)
    try:
        await run_forever(adapters, storage)
    finally:
        storage.close()


async def _test_adapter(source: str) -> None:
    settings = Settings()
    adapters = {adapter.name: adapter for adapter in build_adapters(settings)}
    adapter = adapters.get(source)
    if adapter is None:
        print(f"Unknown or unconfigured adapter: {source}")
        return
    events = await adapter.fetch()
    for event in events:
        print(event)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest" and args.ingest_command == "run":
        asyncio.run(_run_ingest())
    elif args.command == "ingest" and args.ingest_command == "test":
        asyncio.run(_test_adapter(args.source))
```

Replace the contents of `src/hello_coin/__init__.py` with:

```python
from hello_coin.cli import main

__all__ = ["main"]
```

Delete `tests/test_main.py` — it tested the placeholder `"Hello from hello-coin!"` greeting that
`main()` no longer prints; `tests/test_cli.py` covers the new `main()` behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -v`
Expected: all tests pass (the deleted `test_main.py` no longer runs; every other test from
Tasks 2-8 plus the two new CLI tests pass).

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/cli.py src/hello_coin/__init__.py tests/test_cli.py
git rm tests/test_main.py
git commit -m "Wire CLI entry point for ingest run/test commands"
```

---

### Task 10: Real-API smoke test, docs, and manual end-to-end verification

**Files:**
- Create: `tests/ingestion/test_hyperliquid_smoke.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Write the network smoke test**

Create `tests/ingestion/test_hyperliquid_smoke.py`:

```python
import pytest

from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

# A syntactically valid but arbitrary address — Hyperliquid's public info endpoint
# returns an empty fills list for an address with no history rather than erroring,
# so this only asserts the real API is reachable and the response parses cleanly.
PLACEHOLDER_ADDRESS = "0x" + "0" * 40


@pytest.mark.network
@pytest.mark.asyncio
async def test_fetch_reaches_real_hyperliquid_api():
    settings = Settings(hyperliquid_watch_addresses=[PLACEHOLDER_ADDRESS])
    adapter = HyperliquidAdapter(settings)

    events = await adapter.fetch()

    assert isinstance(events, list)
    assert all(isinstance(event, WhaleEvent) for event in events)
```

- [ ] **Step 2: Run it against the real API**

Run: `uv run pytest tests/ingestion/test_hyperliquid_smoke.py -m network -v`
Expected: `1 passed` (confirms the real Hyperliquid endpoint is reachable and the response
shape still matches what `_parse_fill` expects; not run by plain `uv run pytest`).

- [ ] **Step 3: Commit**

```bash
git add tests/ingestion/test_hyperliquid_smoke.py
git commit -m "Add network-marked smoke test against the real Hyperliquid API"
```

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, replace the paragraph that currently reads:

```
The project currently has only the `uv init --package` scaffold plus `pytest`/`ruff` as dev dependencies — no
whale-tracking, indicator, decision, or execution code has been written yet. Update this section (and add an
Architecture section) once real modules exist; don't invent structure ahead of the code.
```

with:

```
## Architecture

`src/hello_coin/ingestion/` is the whale-data ingestion layer (see
`docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md` for the full design):

- `models.py` — `WhaleEvent` (discrete per-wallet actions) and `WhaleMetric` (aggregate
  indicators), the two normalized shapes every adapter produces.
- `adapters/base.py` — `Adapter` abstract base: subclasses implement only `fetch()`;
  `safe_fetch()` handles logging and disabling a source after repeated failures.
- `adapters/*.py` — one file per data source. Only `hyperliquid.py` exists so far.
- `registry.py` — builds the list of adapters whose `is_configured()` is true.
- `storage.py` — SQLite (`data/whale.db`, gitignored) with dedup on `(source, dedup_key)`.
- `scheduler.py` — runs every configured adapter concurrently, each on its own
  `poll_interval_seconds`.
- `config.py` — `pydantic-settings` reading `.env` (see `.env.example`); every adapter's
  credentials are optional, so the service runs with whatever subset is configured.

`src/hello_coin/cli.py` is the entry point: `hello-coin ingest run` starts the service,
`hello-coin ingest test <source>` fetches once from one adapter and prints the result.

No decision engine, technical indicators, or trade execution code exists yet — those are
separate, not-yet-planned pieces of the product intent below.
```

- [ ] **Step 5: Update README.md**

Add to `README.md`, after the "Run" section:

```markdown
## Whale ingestion

1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
2. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
3. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.
```

- [ ] **Step 6: Manually verify against the real Hyperliquid API**

This step is a manual check, not an automated test — it needs a real wallet address:

1. Open https://app.hyperliquid.xyz/leaderboard in a browser and copy any address.
2. Run:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and set `HYPERLIQUID_WATCH_ADDRESSES=<the address you copied>`.
3. Run: `uv run hello-coin ingest test hyperliquid`
   Expected: either prints one `WhaleEvent(...)` line per fill from the last hour, or prints
   nothing if that wallet had no fills in the last hour (try a different, more active address
   from the leaderboard if so).
4. Run: `uv run hello-coin ingest run`, let it run for ~30 seconds, then stop it (Ctrl+C).
   Expected: log lines like `hyperliquid: inserted N new row(s)`, and `data/whale.db` exists.

- [ ] **Step 7: Run the full test suite one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the ingestion architecture and how to run it"
```
