# Liquidation Heatmap Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Coinglass-sourced liquidation heatmap as a third weighted signal (60/25/15 with
whale/technical, falling back to the existing 70/30 whale/technical split when the heatmap is
unavailable) that also gives the decision engine's LLM concrete price levels for entry/exit and
stop-loss/take-profit placement.

**Architecture:** New `src/hello_coin/liquidation/` module mirrors `technical/`'s single-source,
one-snapshot-per-poll layout (models, fetch, pure scoring function, service, SQLite storage,
scheduler) rather than the multi-adapter `ingestion/` pattern. `decision/service.py` reads the
latest stored snapshot, scores it, and folds both the score and the nearest cluster prices into
the existing LLM decision flow.

**Tech Stack:** Python 3.12, `httpx` (async HTTP), `pydantic-settings` (config), stdlib `sqlite3`,
`pytest` + `pytest-asyncio` + `respx` (tests). No new dependencies required.

See `docs/superpowers/specs/2026-08-22-liquidation-heatmap-design.md` for the full design
rationale.

---

### Task 1: Liquidation data models

**Files:**
- Create: `src/hello_coin/liquidation/__init__.py`
- Create: `src/hello_coin/liquidation/models.py`
- Test: `tests/liquidation/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_models.py
from datetime import UTC, datetime

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def test_liquidation_snapshot_holds_fields():
    snapshot = LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=61234.5,
        buckets=[
            LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
            LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
        ],
    )

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.current_price == 61234.5
    assert len(snapshot.buckets) == 2
    assert snapshot.buckets[0].price == 60000.0
    assert snapshot.buckets[0].notional_usd == 1_500_000.0


def test_liquidation_buckets_compare_by_value():
    assert LiquidationBucket(price=100.0, notional_usd=5.0) == LiquidationBucket(
        price=100.0, notional_usd=5.0
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation'`

- [ ] **Step 3: Create the empty package `__init__.py`**

```python
# src/hello_coin/liquidation/__init__.py
```

(empty file, matching `technical/__init__.py` and `decision/__init__.py`)

- [ ] **Step 4: Write the models**

```python
# src/hello_coin/liquidation/models.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LiquidationBucket:
    """One price level in a liquidation heatmap and the estimated leveraged
    value that liquidates at that price."""

    price: float
    notional_usd: float


@dataclass(frozen=True)
class LiquidationSnapshot:
    """A point-in-time liquidation heatmap for one symbol. Buckets don't
    carry a long/short side field — a bucket below `current_price` is a
    long-liquidation cluster (longs get force-sold as price falls), one
    above is a short-liquidation cluster (shorts get force-bought as price
    rises); side is derived at scoring time, not stored."""

    symbol: str
    timestamp: datetime
    current_price: float
    buckets: list[LiquidationBucket]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/liquidation/__init__.py src/hello_coin/liquidation/models.py tests/liquidation/test_models.py
git commit -m "feat: add liquidation heatmap data models"
```

---

### Task 2: Liquidation scoring (pure functions)

**Files:**
- Create: `src/hello_coin/liquidation/score.py`
- Test: `tests/liquidation/test_score.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_score.py
from datetime import UTC, datetime

import pytest

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.score import compute_liquidation_score, nearest_clusters

TIMESTAMP = datetime(2026, 8, 22, tzinfo=UTC)

BUCKETS = [
    LiquidationBucket(price=95.0, notional_usd=1_000_000.0),  # long, distance_pct=0.05
    LiquidationBucket(price=90.0, notional_usd=500_000.0),  # long, distance_pct=0.10 (boundary)
    LiquidationBucket(price=105.0, notional_usd=2_000_000.0),  # short, distance_pct=0.05
    LiquidationBucket(price=120.0, notional_usd=800_000.0),  # short, distance_pct=0.20
]


def _snapshot(buckets: list[LiquidationBucket]) -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT", timestamp=TIMESTAMP, current_price=100.0, buckets=buckets
    )


def test_compute_liquidation_score_weighs_nearby_clusters_by_inverse_distance():
    # Reference calculation (current_price=100, proximity_pct=0.10 default):
    # long @95:  distance=0.05, weight=1,000,000/0.05=20,000,000
    # long @90:  distance=0.10 (boundary, included), weight=500,000/0.10=5,000,000
    # short @105: distance=0.05, weight=2,000,000/0.05=40,000,000
    # short @120: distance=0.20 > 0.10, excluded
    # weighted_long=25,000,000, weighted_short=40,000,000, total=65,000,000
    # score=(40,000,000-25,000,000)/65,000,000=0.23076923076923078
    result = compute_liquidation_score(_snapshot(BUCKETS))
    assert result == pytest.approx(0.23076923076923078)


def test_compute_liquidation_score_excludes_bucket_at_current_price():
    buckets = [LiquidationBucket(price=100.0, notional_usd=999_999.0)]
    assert compute_liquidation_score(_snapshot(buckets)) is None


def test_compute_liquidation_score_is_none_when_nothing_in_proximity():
    buckets = [LiquidationBucket(price=150.0, notional_usd=1_000_000.0)]
    assert compute_liquidation_score(_snapshot(buckets)) is None


def test_compute_liquidation_score_respects_custom_proximity_pct():
    # With proximity_pct=0.25 the @120 short cluster (distance 0.20) is now included:
    # weighted_short += 800,000/0.20=4,000,000 -> weighted_short=44,000,000
    # weighted_long stays 25,000,000, total=69,000,000
    # score=(44,000,000-25,000,000)/69,000,000=0.2753623188405797
    result = compute_liquidation_score(_snapshot(BUCKETS), proximity_pct=0.25)
    assert result == pytest.approx(0.2753623188405797)


def test_nearest_clusters_returns_top_n_by_notional_per_side():
    result = nearest_clusters(_snapshot(BUCKETS), n=2)

    assert result["long_below"] == [(95.0, 1_000_000.0), (90.0, 500_000.0)]
    assert result["short_above"] == [(105.0, 2_000_000.0), (120.0, 800_000.0)]


def test_nearest_clusters_respects_n():
    result = nearest_clusters(_snapshot(BUCKETS), n=1)

    assert result["long_below"] == [(95.0, 1_000_000.0)]
    assert result["short_above"] == [(105.0, 2_000_000.0)]


def test_nearest_clusters_empty_side_returns_empty_list():
    buckets = [LiquidationBucket(price=105.0, notional_usd=2_000_000.0)]
    result = nearest_clusters(_snapshot(buckets))

    assert result["long_below"] == []
    assert result["short_above"] == [(105.0, 2_000_000.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation.score'`

- [ ] **Step 3: Write the scoring functions**

```python
# src/hello_coin/liquidation/score.py
from hello_coin.liquidation.models import LiquidationSnapshot


def compute_liquidation_score(
    snapshot: LiquidationSnapshot, proximity_pct: float = 0.10
) -> float | None:
    """Weighs nearby short-liquidation clusters (bullish magnet — price tends
    to get pulled up to sweep them) against nearby long-liquidation clusters
    (bearish magnet) into a single [-1, 1] score. Clusters farther than
    `proximity_pct` away don't inform near-term entry/exit decisions and are
    excluded; a bucket exactly at the current price has no defined side and
    is excluded too."""
    current_price = snapshot.current_price
    weighted_long = 0.0
    weighted_short = 0.0
    for bucket in snapshot.buckets:
        distance_pct = abs(bucket.price - current_price) / current_price
        if distance_pct == 0 or distance_pct > proximity_pct:
            continue
        weight = bucket.notional_usd / distance_pct
        if bucket.price < current_price:
            weighted_long += weight
        else:
            weighted_short += weight

    total = weighted_long + weighted_short
    if total == 0:
        return None
    return (weighted_short - weighted_long) / total


def nearest_clusters(
    snapshot: LiquidationSnapshot, n: int = 2
) -> dict[str, list[tuple[float, float]]]:
    """Top-N clusters per side by notional value, as (price, notional_usd)
    pairs — concrete levels for the decision LLM's entry/exit/stop-loss
    context, not a score. Not proximity-filtered: a large cluster further
    out can still be a meaningful target."""
    current_price = snapshot.current_price
    long_clusters = sorted(
        (b for b in snapshot.buckets if b.price < current_price),
        key=lambda b: b.notional_usd,
        reverse=True,
    )[:n]
    short_clusters = sorted(
        (b for b in snapshot.buckets if b.price > current_price),
        key=lambda b: b.notional_usd,
        reverse=True,
    )[:n]
    return {
        "long_below": [(b.price, b.notional_usd) for b in long_clusters],
        "short_above": [(b.price, b.notional_usd) for b in short_clusters],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_score.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/liquidation/score.py tests/liquidation/test_score.py
git commit -m "feat: add liquidation heatmap scoring"
```

---

### Task 3: Coinglass config settings

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `.env.example`
- Modify: `tests/ingestion/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/test_config.py`:

```python
def test_liquidation_settings_default(monkeypatch):
    for var in (
        "COINGLASS_API_KEY",
        "LIQUIDATION_PROXIMITY_PCT",
        "LIQUIDATION_POLL_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.coinglass_api_key is None
    assert settings.liquidation_proximity_pct == 0.10
    assert settings.liquidation_poll_interval_seconds == 900


def test_liquidation_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "cg-test-key")
    monkeypatch.setenv("LIQUIDATION_PROXIMITY_PCT", "0.05")
    monkeypatch.setenv("LIQUIDATION_POLL_INTERVAL_SECONDS", "300")

    settings = Settings(_env_file=None)

    assert settings.coinglass_api_key == "cg-test-key"
    assert settings.liquidation_proximity_pct == 0.05
    assert settings.liquidation_poll_interval_seconds == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_config.py -k liquidation -v`
Expected: FAIL with `AttributeError` (`Settings` has no field `coinglass_api_key`)

- [ ] **Step 3: Add the settings**

In `src/hello_coin/ingestion/config.py`, add after `decision_whale_lookback_hours: int = 24`:

```python
    coinglass_api_key: str | None = None
    liquidation_proximity_pct: float = 0.10
    liquidation_poll_interval_seconds: int = 900
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Document the new env vars**

Append to `.env.example`:

```
# Coinglass API key (coinglass.com, paid — required for the liquidation-heatmap signal).
# LIQUIDATION_PROXIMITY_PCT controls how far (as a fraction of price) a liquidation cluster
# can be from the current price and still count toward liquidation_score. The response shape
# is not first-party-confirmed — see
# docs/superpowers/specs/2026-08-22-liquidation-heatmap-design.md.
COINGLASS_API_KEY=
LIQUIDATION_PROXIMITY_PCT=0.10
LIQUIDATION_POLL_INTERVAL_SECONDS=900
```

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/config.py .env.example tests/ingestion/test_config.py
git commit -m "feat: add Coinglass liquidation config settings"
```

---

### Task 4: Coinglass HTTP fetch

**Files:**
- Create: `src/hello_coin/liquidation/coinglass.py`
- Test: `tests/liquidation/test_coinglass.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_coinglass.py
import httpx
import pytest
import respx

from hello_coin.ingestion.config import Settings
from hello_coin.liquidation.coinglass import COINGLASS_HEATMAP_URL, fetch_heatmap, is_configured

HEATMAP_RESPONSE = {
    "code": "0",
    "data": {
        "current_price": 61234.5,
        "buckets": [
            {"price": 60000.0, "leverage_value_usd": 1_500_000.0},
            {"price": 63000.0, "leverage_value_usd": 2_000_000.0},
        ],
    },
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(coinglass_api_key="test-key")
    assert is_configured(settings) is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(coinglass_api_key=None)
    assert is_configured(settings) is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_heatmap_sends_api_key_header_and_symbol_param():
    route = respx.get(COINGLASS_HEATMAP_URL).mock(
        return_value=httpx.Response(200, json=HEATMAP_RESPONSE)
    )

    payload = await fetch_heatmap("BTCUSDT", "test-key")

    assert payload == HEATMAP_RESPONSE
    request = route.calls[0].request
    assert request.headers["CG-API-KEY"] == "test-key"
    assert request.url.params["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_heatmap_raises_on_http_error():
    respx.get(COINGLASS_HEATMAP_URL).mock(return_value=httpx.Response(401, json={"code": "401"}))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_heatmap("BTCUSDT", "bad-key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_coinglass.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation.coinglass'`

- [ ] **Step 3: Write the fetch module**

```python
# src/hello_coin/liquidation/coinglass.py
import httpx

from hello_coin.ingestion.config import Settings

COINGLASS_HEATMAP_URL = "https://open-api-v4.coinglass.com/api/futures/liquidation-heatmap"


def is_configured(settings: Settings) -> bool:
    return bool(settings.coinglass_api_key)


async def fetch_heatmap(symbol: str, api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            COINGLASS_HEATMAP_URL,
            params={"symbol": symbol},
            headers={"CG-API-KEY": api_key},
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_coinglass.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/liquidation/coinglass.py tests/liquidation/test_coinglass.py
git commit -m "feat: add Coinglass liquidation-heatmap fetch"
```

---

### Task 5: Liquidation snapshot service (fetch + parse)

**Files:**
- Create: `src/hello_coin/liquidation/service.py`
- Test: `tests/liquidation/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_service.py
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.liquidation.service import compute_snapshot

HEATMAP_RESPONSE = {
    "code": "0",
    "data": {
        "current_price": 61234.5,
        "buckets": [
            {"price": 60000.0, "leverage_value_usd": 1_500_000.0},
            {"price": 63000.0, "leverage_value_usd": 2_000_000.0},
        ],
    },
}


@pytest.mark.asyncio
async def test_compute_snapshot_parses_heatmap_into_buckets():
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap",
        new=AsyncMock(return_value=HEATMAP_RESPONSE),
    ) as mock_fetch:
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    mock_fetch.assert_awaited_once_with("BTCUSDT", "test-key")
    assert snapshot is not None
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.current_price == 61234.5
    assert len(snapshot.buckets) == 2
    assert snapshot.buckets[0].price == 60000.0
    assert snapshot.buckets[0].notional_usd == 1_500_000.0


@pytest.mark.asyncio
async def test_compute_snapshot_returns_none_when_data_missing():
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap",
        new=AsyncMock(return_value={"code": "0"}),
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is None


@pytest.mark.asyncio
async def test_compute_snapshot_skips_buckets_missing_fields():
    response = {
        "code": "0",
        "data": {
            "current_price": 100.0,
            "buckets": [{"price": 95.0}, {"price": 105.0, "leverage_value_usd": 10.0}],
        },
    }
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap", new=AsyncMock(return_value=response)
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is not None
    assert len(snapshot.buckets) == 1
    assert snapshot.buckets[0].price == 105.0


@pytest.mark.asyncio
async def test_compute_snapshot_returns_none_when_all_buckets_unparseable():
    response = {"code": "0", "data": {"current_price": 100.0, "buckets": [{"price": 95.0}]}}
    with patch(
        "hello_coin.liquidation.service.fetch_heatmap", new=AsyncMock(return_value=response)
    ):
        snapshot = await compute_snapshot("BTCUSDT", "test-key")

    assert snapshot is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation.service'`

- [ ] **Step 3: Write the service**

```python
# src/hello_coin/liquidation/service.py
from datetime import UTC, datetime

from hello_coin.liquidation.coinglass import fetch_heatmap
from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def _parse_bucket(row: dict) -> LiquidationBucket | None:
    """Field names here are an assumed shape — Coinglass's heatmap response
    has not been first-party-confirmed against a real key (same caveat as
    whale_alert.py/bitquery.py). Every access is defensive so a shape
    mismatch skips this row instead of raising."""
    price = row.get("price")
    notional_usd = row.get("leverage_value_usd")
    if price is None or notional_usd is None:
        return None
    return LiquidationBucket(price=float(price), notional_usd=float(notional_usd))


async def compute_snapshot(symbol: str, api_key: str) -> LiquidationSnapshot | None:
    payload = await fetch_heatmap(symbol, api_key)
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    current_price = data.get("current_price")
    rows = data.get("buckets")
    if current_price is None or not isinstance(rows, list):
        return None

    buckets = [b for row in rows if (b := _parse_bucket(row)) is not None]
    if not buckets:
        return None

    return LiquidationSnapshot(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        current_price=float(current_price),
        buckets=buckets,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_service.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/liquidation/service.py tests/liquidation/test_service.py
git commit -m "feat: add liquidation snapshot service"
```

---

### Task 6: Liquidation SQLite storage

**Files:**
- Create: `src/hello_coin/liquidation/storage.py`
- Test: `tests/liquidation/test_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_storage.py
from datetime import UTC, datetime

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.storage import LiquidationStorage


def _snapshot(timestamp: datetime) -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=timestamp,
        current_price=61234.5,
        buckets=[
            LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
            LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
        ],
    )


def test_insert_snapshot_returns_count_and_dedupes():
    storage = LiquidationStorage(":memory:")
    first = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timestamp
    third = _snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC))

    inserted_first = storage.insert_snapshot(first)
    inserted_second = storage.insert_snapshot(second)
    inserted_third = storage.insert_snapshot(third)

    assert inserted_first == 1
    assert inserted_second == 0
    assert inserted_third == 1
    assert storage.count_snapshots() == 2
    assert storage.count_snapshots(symbol="BTCUSDT") == 2
    assert storage.count_snapshots(symbol="ETHUSDT") == 0


def test_latest_snapshot_returns_most_recent_reconstructed_snapshot():
    storage = LiquidationStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))

    latest = storage.latest_snapshot("BTCUSDT")

    assert latest is not None
    assert latest.timestamp == datetime(2026, 8, 22, 1, tzinfo=UTC)
    assert latest.current_price == 61234.5
    assert latest.buckets == [
        LiquidationBucket(price=60000.0, notional_usd=1_500_000.0),
        LiquidationBucket(price=63000.0, notional_usd=2_000_000.0),
    ]


def test_latest_snapshot_returns_none_when_no_rows():
    storage = LiquidationStorage(":memory:")

    assert storage.latest_snapshot("ETHUSDT") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation.storage'`

- [ ] **Step 3: Write the storage**

```python
# src/hello_coin/liquidation/storage.py
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS liquidation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    current_price REAL NOT NULL,
    buckets TEXT NOT NULL,
    UNIQUE(symbol, timestamp)
)
"""


class LiquidationStorage:
    """SQLite-backed storage for liquidation heatmap snapshots. No business
    logic — just insert (deduped) and basic reads for later consumers.
    `latest_snapshot` reconstructs a full `LiquidationSnapshot` (not a flat
    dict) since `liquidation/score.py`'s functions operate on that shape."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_snapshot(self, snapshot: LiquidationSnapshot) -> int:
        buckets_json = json.dumps([[b.price, b.notional_usd] for b in snapshot.buckets])
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO liquidation_snapshots
                (symbol, timestamp, current_price, buckets)
            VALUES (?, ?, ?, ?)
            """,
            (
                snapshot.symbol,
                snapshot.timestamp.isoformat(),
                snapshot.current_price,
                buckets_json,
            ),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_snapshots(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute("SELECT COUNT(*) FROM liquidation_snapshots").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM liquidation_snapshots WHERE symbol = ?", (symbol,)
            ).fetchone()
        return int(row[0])

    def latest_snapshot(self, symbol: str) -> LiquidationSnapshot | None:
        row = self._conn.execute(
            """
            SELECT symbol, timestamp, current_price, buckets
            FROM liquidation_snapshots
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        symbol_value, timestamp, current_price, buckets_json = row
        buckets = [
            LiquidationBucket(price=price, notional_usd=notional_usd)
            for price, notional_usd in json.loads(buckets_json)
        ]
        return LiquidationSnapshot(
            symbol=symbol_value,
            timestamp=datetime.fromisoformat(timestamp),
            current_price=current_price,
            buckets=buckets,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_storage.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/liquidation/storage.py tests/liquidation/test_storage.py
git commit -m "feat: add liquidation SQLite storage"
```

---

### Task 7: Liquidation poll scheduler

**Files:**
- Create: `src/hello_coin/liquidation/scheduler.py`
- Test: `tests/liquidation/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidation/test_scheduler.py
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot
from hello_coin.liquidation.scheduler import poll_once, run_symbol_loop
from hello_coin.liquidation.storage import LiquidationStorage


def _snapshot() -> LiquidationSnapshot:
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=61234.5,
        buckets=[LiquidationBucket(price=60000.0, notional_usd=1_500_000.0)],
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_snapshot_and_returns_count():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(return_value=_snapshot()),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 1
    assert storage.count_snapshots() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_when_snapshot_is_none():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(return_value=None),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_fetch_failure():
    storage = LiquidationStorage(":memory:")
    with patch(
        "hello_coin.liquidation.scheduler.compute_snapshot",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once("BTCUSDT", "test-key", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = LiquidationStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_snapshot(symbol, api_key):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _snapshot()

    with patch("hello_coin.liquidation.scheduler.compute_snapshot", new=_fake_compute_snapshot):
        await run_symbol_loop("BTCUSDT", "test-key", storage, stop_event, poll_interval_seconds=0)

    assert call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/liquidation/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.liquidation.scheduler'`

- [ ] **Step 3: Write the scheduler**

```python
# src/hello_coin/liquidation/scheduler.py
import asyncio
import logging

from hello_coin.liquidation.service import compute_snapshot
from hello_coin.liquidation.storage import LiquidationStorage

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 900  # 15 min — heatmaps don't change fast; Coinglass is paid


async def poll_once(symbol: str, api_key: str, storage: LiquidationStorage) -> int:
    try:
        snapshot = await compute_snapshot(symbol, api_key)
    except Exception:
        logger.exception("%s: liquidation snapshot fetch failed", symbol)
        return 0
    if snapshot is None:
        return 0
    return storage.insert_snapshot(snapshot)


async def run_symbol_loop(
    symbol: str,
    api_key: str,
    storage: LiquidationStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(symbol, api_key, storage)
        logger.info("%s: inserted %d new row(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str],
    api_key: str,
    storage: LiquidationStorage,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(symbol, api_key, storage, stop_event, poll_interval_seconds)
            for symbol in symbols
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/liquidation/test_scheduler.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/liquidation/scheduler.py tests/liquidation/test_scheduler.py
git commit -m "feat: add liquidation poll scheduler"
```

---

### Task 8: Add `liquidation_score` to the `Decision` model

**Files:**
- Modify: `src/hello_coin/decision/models.py`
- Modify: `tests/decision/test_models.py`

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/decision/test_models.py`:

```python
from datetime import UTC, datetime

from hello_coin.decision.models import Decision


def test_decision_holds_fields():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        whale_score=0.49,
        technical_score=0.475,
        liquidation_score=0.23,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Whale accumulation and bullish momentum align.",
        raw={"model": "claude-sonnet-5"},
    )

    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.liquidation_score == 0.23
    assert decision.raw == {"model": "claude-sonnet-5"}


def test_decision_allows_none_scores():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        whale_score=None,
        technical_score=0.475,
        liquidation_score=None,
        weighted_score=None,
        action="hold",
        confidence=0.4,
        reasoning="No whale data available; technical signal alone is inconclusive.",
        raw={},
    )

    assert decision.whale_score is None
    assert decision.liquidation_score is None
    assert decision.weighted_score is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_models.py -v`
Expected: FAIL with `TypeError: Decision.__init__() got an unexpected keyword argument 'liquidation_score'`

- [ ] **Step 3: Add the field**

In `src/hello_coin/decision/models.py`, insert `liquidation_score: float | None` between
`technical_score: float | None` and `weighted_score: float | None`:

```python
@dataclass(frozen=True)
class Decision:
    """One AI-made trade decision for a symbol at a point in time."""

    symbol: str
    timestamp: datetime
    whale_score: float | None
    technical_score: float | None
    liquidation_score: float | None
    weighted_score: float | None
    action: str  # "buy" | "sell" | "hold"
    confidence: float
    reasoning: str
    raw: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/models.py tests/decision/test_models.py
git commit -m "feat: add liquidation_score field to Decision"
```

---

### Task 9: Add `liquidation_score` column to decision storage

**Files:**
- Modify: `src/hello_coin/decision/storage.py`
- Modify: `tests/decision/test_storage.py`

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/decision/test_storage.py`:

```python
from datetime import UTC, datetime

from hello_coin.decision.models import Decision
from hello_coin.decision.storage import DecisionStorage


def _decision(timestamp: datetime) -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=timestamp,
        whale_score=0.49,
        technical_score=0.475,
        liquidation_score=0.23,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Aligned signals.",
        raw={"model": "claude-sonnet-5"},
    )


def test_insert_decision_returns_count_and_dedupes():
    storage = DecisionStorage(":memory:")
    first = _decision(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _decision(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timestamp
    third = _decision(datetime(2026, 8, 22, 1, tzinfo=UTC))

    inserted_first = storage.insert_decision(first)
    inserted_second = storage.insert_decision(second)
    inserted_third = storage.insert_decision(third)

    assert inserted_first == 1
    assert inserted_second == 0
    assert inserted_third == 1
    assert storage.count_decisions() == 2
    assert storage.count_decisions(symbol="BTCUSDT") == 2
    assert storage.count_decisions(symbol="ETHUSDT") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_storage.py -v`
Expected: FAIL with `TypeError` (Decision now requires `liquidation_score`, and/or an
`sqlite3.ProgrammingError` from the column-count mismatch once the model is updated)

- [ ] **Step 3: Update the schema and insert statement**

Replace the full contents of `src/hello_coin/decision/storage.py`:

```python
import json
import sqlite3
from pathlib import Path

from hello_coin.decision.models import Decision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    whale_score REAL,
    technical_score REAL,
    liquidation_score REAL,
    weighted_score REAL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(symbol, timestamp)
)
"""


class DecisionStorage:
    """SQLite-backed storage for AI trade decisions. No business logic —
    just insert (deduped) and basic reads for later consumers."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_decision(self, decision: Decision) -> int:
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO decisions
                (symbol, timestamp, whale_score, technical_score, liquidation_score,
                 weighted_score, action, confidence, reasoning, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.symbol,
                decision.timestamp.isoformat(),
                decision.whale_score,
                decision.technical_score,
                decision.liquidation_score,
                decision.weighted_score,
                decision.action,
                decision.confidence,
                decision.reasoning,
                json.dumps(decision.raw),
            ),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_decisions(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE symbol = ?", (symbol,)
            ).fetchone()
        return int(row[0])
```

Note: `data/decisions.db` is gitignored, so no migration path is needed for existing local
databases — delete the file if a stale schema causes a column-count error locally.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_storage.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/storage.py tests/decision/test_storage.py
git commit -m "feat: add liquidation_score column to decision storage"
```

---

### Task 10: Integrate liquidation scoring into `decision/service.py`

**Files:**
- Modify: `src/hello_coin/decision/service.py`
- Modify: `tests/decision/test_service.py`

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/decision/test_service.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.service import compute_decision
from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def _liquidation_snapshot() -> LiquidationSnapshot:
    # Single short cluster at 105 with current_price=100 -> distance_pct=0.05,
    # weighted_short=1,000,000/0.05=20,000,000, weighted_long=0 -> score=1.0
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=100.0,
        buckets=[LiquidationBucket(price=105.0, notional_usd=1_000_000.0)],
    )


def _technical_snapshot() -> dict:
    return {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
        "atr": 2.0,
    }


@pytest.mark.asyncio
async def test_compute_decision_combines_all_three_scores_and_calls_llm():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = [{"side": "buy", "amount_usd": 300.0}]
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = _liquidation_snapshot()

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "buy", "confidence": 0.8, "reasoning": "Aligned signals."}
        ),
    ) as mock_request_decision:
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.symbol == "BTCUSDT"
    assert decision.whale_score == pytest.approx(1.0)  # all-buy volume_bias
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.liquidation_score == pytest.approx(1.0)
    assert decision.weighted_score == pytest.approx(0.60 * 1.0 + 0.25 * 0.475 + 0.15 * 1.0)
    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.reasoning == "Aligned signals."

    liquidation_storage.latest_snapshot.assert_called_once_with("BTCUSDT")
    mock_request_decision.assert_awaited_once()
    call_kwargs = mock_request_decision.call_args.kwargs
    # The single short cluster at 105 should show up as concrete entry/exit context,
    # not the "unavailable" placeholder used when there's no liquidation snapshot.
    assert "short_above=[(105.0, 1000000.0)]" in call_kwargs["user_message"]


@pytest.mark.asyncio
async def test_compute_decision_falls_back_to_two_signal_weighting_when_liquidation_missing():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = [{"side": "buy", "amount_usd": 300.0}]
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = None

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "buy", "confidence": 0.8, "reasoning": "Aligned signals."}
        ),
    ):
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.liquidation_score is None
    assert decision.weighted_score == pytest.approx(0.7 * 1.0 + 0.3 * 0.475)


@pytest.mark.asyncio
async def test_compute_decision_reports_missing_data_without_reweighting():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = []
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = None

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "hold", "confidence": 0.3, "reasoning": "No whale data."}
        ),
    ):
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.whale_score is None
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.weighted_score is None  # never re-weighted to 100% technical
```

Note on the slightly awkward assertion in the first test: it's checking that when a liquidation
snapshot is available, the `long_below`/`short_above` cluster context actually appears in the
prompt text rather than the `"unavailable"` placeholder — this is what makes the "concrete
entry/exit price levels" behavior from the spec observable in a unit test.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_service.py -v`
Expected: FAIL with `TypeError: compute_decision() got an unexpected keyword argument 'liquidation_storage'`

- [ ] **Step 3: Update the service**

Replace the full contents of `src/hello_coin/decision/service.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any

from hello_coin.decision.llm import request_decision
from hello_coin.decision.models import Decision
from hello_coin.decision.technical_score import compute_technical_score
from hello_coin.decision.whale_score import base_asset, compute_whale_score
from hello_coin.liquidation.score import compute_liquidation_score, nearest_clusters

SYSTEM_PROMPT = (
    "You are a crypto trading decision assistant for the hello-coin system. Whale activity, "
    "technical indicators, and the liquidation heatmap are combined into weighted_score: when "
    "all three signals are available, whale carries 60%, technical 25%, and liquidation 15% of "
    "the weight; when the liquidation signal is unavailable, whale carries 70% and technical "
    "30%, exactly as before this signal existed — treat weighted_score's value as authoritative "
    "rather than assuming a fixed split. Scores range from -1 (strongly bearish) to +1 "
    "(strongly bullish); a missing score means that data source had nothing usable this cycle, "
    "not that it's neutral — factor the gap into your confidence rather than ignoring it. When "
    "liquidation cluster prices are provided, use them as concrete levels for entry/exit timing "
    "and stop-loss/take-profit placement, not just for direction. Always call the decide tool."
)


def _build_user_message(
    symbol: str,
    whale_score: float | None,
    technical_score: float | None,
    liquidation_score: float | None,
    weighted_score: float | None,
    snapshot: dict[str, Any] | None,
    clusters: dict[str, list[tuple[float, float]]] | None,
) -> str:
    lines = [f"Symbol: {symbol}"]
    lines.append(f"whale_score: {whale_score if whale_score is not None else 'unavailable'}")
    lines.append(
        f"technical_score: {technical_score if technical_score is not None else 'unavailable'}"
    )
    lines.append(
        "liquidation_score: "
        f"{liquidation_score if liquidation_score is not None else 'unavailable'}"
    )
    if weighted_score is not None:
        weighted_display = str(weighted_score)
    else:
        weighted_display = "unavailable (fewer than two inputs available)"
    lines.append(f"weighted_score: {weighted_display}")
    if snapshot is not None:
        lines.append(
            "Latest technical readings: "
            f"close={snapshot.get('close_price')}, rsi={snapshot.get('rsi')}, "
            f"macd_histogram={snapshot.get('macd_histogram')}, "
            f"bollinger=({snapshot.get('bb_lower')}, {snapshot.get('bb_middle')}, "
            f"{snapshot.get('bb_upper')}), ema={snapshot.get('ema')}, atr={snapshot.get('atr')}"
        )
    if clusters is not None:
        lines.append(
            "Nearest liquidation clusters (price, notional_usd): "
            f"long_below={clusters['long_below']}, short_above={clusters['short_above']}"
        )
    return "\n".join(lines)


async def compute_decision(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    liquidation_proximity_pct: float = 0.10,
) -> Decision:
    since = datetime.now(tz=UTC) - timedelta(hours=whale_lookback_hours)
    asset = base_asset(symbol)

    events = whale_storage.recent_events(asset, since)
    metrics = whale_storage.recent_metrics(symbol, since) + whale_storage.recent_metrics(
        asset, since
    )
    whale_score = compute_whale_score(events, metrics)

    snapshot = technical_storage.latest_snapshot(symbol, timeframe)
    technical_score = compute_technical_score(snapshot) if snapshot is not None else None

    liq_snapshot = liquidation_storage.latest_snapshot(symbol)
    liquidation_score = (
        compute_liquidation_score(liq_snapshot, liquidation_proximity_pct)
        if liq_snapshot is not None
        else None
    )
    clusters = nearest_clusters(liq_snapshot) if liq_snapshot is not None else None

    if whale_score is not None and technical_score is not None and liquidation_score is not None:
        weighted_score = 0.60 * whale_score + 0.25 * technical_score + 0.15 * liquidation_score
    elif whale_score is not None and technical_score is not None:
        weighted_score = 0.7 * whale_score + 0.3 * technical_score
    else:
        weighted_score = None

    user_message = _build_user_message(
        symbol,
        whale_score,
        technical_score,
        liquidation_score,
        weighted_score,
        snapshot,
        clusters,
    )
    result = await request_decision(
        client=anthropic_client, model=model, system=SYSTEM_PROMPT, user_message=user_message
    )

    return Decision(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        whale_score=whale_score,
        technical_score=technical_score,
        liquidation_score=liquidation_score,
        weighted_score=weighted_score,
        action=result["action"],
        confidence=float(result["confidence"]),
        reasoning=result["reasoning"],
        raw=result,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/service.py tests/decision/test_service.py
git commit -m "feat: integrate liquidation score into decision engine"
```

---

### Task 11: Thread `liquidation_storage` through `decision/scheduler.py`

**Files:**
- Modify: `src/hello_coin/decision/scheduler.py`
- Modify: `tests/decision/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/decision/test_scheduler.py`:

```python
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.models import Decision
from hello_coin.decision.scheduler import poll_once, run_symbol_loop
from hello_coin.decision.storage import DecisionStorage


def _decision() -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        whale_score=0.49,
        technical_score=0.475,
        liquidation_score=0.23,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Aligned signals.",
        raw={},
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_decision_and_returns_count():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(return_value=_decision()),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            liquidation_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 1
    assert storage.count_decisions() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_failure():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            liquidation_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 0
    assert storage.count_decisions() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = DecisionStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_decision(**kwargs):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _decision()

    with patch("hello_coin.decision.scheduler.compute_decision", new=_fake_compute_decision):
        await run_symbol_loop(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            liquidation_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
            stop_event=stop_event,
            poll_interval_seconds=0,
        )

    assert call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_scheduler.py -v`
Expected: FAIL with `TypeError: poll_once() got an unexpected keyword argument 'liquidation_storage'`

- [ ] **Step 3: Update the scheduler**

Replace the full contents of `src/hello_coin/decision/scheduler.py`:

```python
import asyncio
import logging
from typing import Any

from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 3600  # 1 hour — matches the technical layer's 1h candle default


async def poll_once(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    liquidation_proximity_pct: float = 0.10,
) -> int:
    try:
        decision = await compute_decision(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
            liquidation_proximity_pct=liquidation_proximity_pct,
        )
    except Exception:
        logger.exception("%s: decision failed", symbol)
        return 0
    return storage.insert_decision(decision)


async def run_symbol_loop(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
    liquidation_proximity_pct: float = 0.10,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
            storage=storage,
            liquidation_proximity_pct=liquidation_proximity_pct,
        )
        logger.info("%s: inserted %d new decision(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str],
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    liquidation_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    liquidation_proximity_pct: float = 0.10,
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(
                symbol=symbol,
                timeframe=timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=anthropic_client,
                model=model,
                whale_lookback_hours=whale_lookback_hours,
                storage=storage,
                stop_event=stop_event,
                poll_interval_seconds=poll_interval_seconds,
                liquidation_proximity_pct=liquidation_proximity_pct,
            )
            for symbol in symbols
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_scheduler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/scheduler.py tests/decision/test_scheduler.py
git commit -m "feat: thread liquidation storage through decision scheduler"
```

---

### Task 12: Wire the CLI (`liquidation run`/`test`, `decision` picks up liquidation storage)

**Files:**
- Modify: `src/hello_coin/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_liquidation_run_parses():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "run"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "run"


def test_liquidation_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "test", "BTCUSDT"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "test"
    assert args.symbol == "BTCUSDT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `argparse.ArgumentError` / `SystemExit` (`liquidation` is not a recognized
command yet)

- [ ] **Step 3: Update the CLI**

Replace the full contents of `src/hello_coin/cli.py`:

```python
import argparse
import asyncio
import logging

from anthropic import AsyncAnthropic

from hello_coin.decision.scheduler import run_forever as run_decision_forever
from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.liquidation.coinglass import is_configured as liquidation_is_configured
from hello_coin.liquidation.scheduler import run_forever as run_liquidation_forever
from hello_coin.liquidation.service import compute_snapshot as compute_liquidation_snapshot
from hello_coin.liquidation.storage import LiquidationStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"
DEFAULT_DECISION_DB_PATH = "data/decisions.db"
DEFAULT_LIQUIDATION_DB_PATH = "data/liquidation.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-coin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Whale data ingestion commands")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)
    ingest_subparsers.add_parser("run", help="Run the ingestion service continuously")
    ingest_test_parser = ingest_subparsers.add_parser(
        "test", help="Fetch once from a single adapter and print the result"
    )
    ingest_test_parser.add_argument("source", help="Adapter name, e.g. hyperliquid")

    technical_parser = subparsers.add_parser("technical", help="Technical indicator commands")
    technical_subparsers = technical_parser.add_subparsers(
        dest="technical_command", required=True
    )
    technical_subparsers.add_parser("run", help="Run the technical-indicators service continuously")
    technical_test_parser = technical_subparsers.add_parser(
        "test", help="Compute one snapshot for a symbol and print the result"
    )
    technical_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    liquidation_parser = subparsers.add_parser("liquidation", help="Liquidation heatmap commands")
    liquidation_subparsers = liquidation_parser.add_subparsers(
        dest="liquidation_command", required=True
    )
    liquidation_subparsers.add_parser(
        "run", help="Run the liquidation-heatmap service continuously"
    )
    liquidation_test_parser = liquidation_subparsers.add_parser(
        "test", help="Fetch one heatmap snapshot for a symbol and print the result"
    )
    liquidation_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    decision_parser = subparsers.add_parser("decision", help="AI decision engine commands")
    decision_subparsers = decision_parser.add_subparsers(dest="decision_command", required=True)
    decision_subparsers.add_parser("run", help="Run the decision engine continuously")
    decision_test_parser = decision_subparsers.add_parser(
        "test", help="Compute one decision for a symbol and print the result"
    )
    decision_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    return parser


async def _run_ingest() -> None:
    settings = Settings()
    adapters = build_adapters(settings)
    storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    try:
        await run_ingestion_forever(adapters, storage)
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


async def _run_technical() -> None:
    settings = Settings()
    storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    try:
        await run_technical_forever(
            settings.exchange_watch_symbols, settings.technical_timeframe, storage
        )
    finally:
        storage.close()


async def _test_technical(symbol: str) -> None:
    settings = Settings()
    snapshot = await compute_snapshot(symbol, settings.technical_timeframe)
    print(snapshot)


async def _run_liquidation() -> None:
    settings = Settings()
    if not liquidation_is_configured(settings):
        print("COINGLASS_API_KEY is not set — the liquidation service is not configured.")
        return
    storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    try:
        await run_liquidation_forever(
            settings.exchange_watch_symbols,
            settings.coinglass_api_key,
            storage,
            poll_interval_seconds=settings.liquidation_poll_interval_seconds,
        )
    finally:
        storage.close()


async def _test_liquidation(symbol: str) -> None:
    settings = Settings()
    if not liquidation_is_configured(settings):
        print("COINGLASS_API_KEY is not set — the liquidation service is not configured.")
        return
    snapshot = await compute_liquidation_snapshot(symbol, settings.coinglass_api_key)
    print(snapshot)


async def _run_decision() -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    liquidation_storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    decision_storage = DecisionStorage(DEFAULT_DECISION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            await run_decision_forever(
                symbols=settings.exchange_watch_symbols,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                storage=decision_storage,
                liquidation_proximity_pct=settings.liquidation_proximity_pct,
            )
    finally:
        whale_storage.close()
        technical_storage.close()
        liquidation_storage.close()
        decision_storage.close()


async def _test_decision(symbol: str) -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    liquidation_storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            decision = await compute_decision(
                symbol=symbol,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                liquidation_proximity_pct=settings.liquidation_proximity_pct,
            )
        print(decision)
    finally:
        whale_storage.close()
        technical_storage.close()
        liquidation_storage.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest" and args.ingest_command == "run":
        asyncio.run(_run_ingest())
    elif args.command == "ingest" and args.ingest_command == "test":
        asyncio.run(_test_adapter(args.source))
    elif args.command == "technical" and args.technical_command == "run":
        asyncio.run(_run_technical())
    elif args.command == "technical" and args.technical_command == "test":
        asyncio.run(_test_technical(args.symbol))
    elif args.command == "liquidation" and args.liquidation_command == "run":
        asyncio.run(_run_liquidation())
    elif args.command == "liquidation" and args.liquidation_command == "test":
        asyncio.run(_test_liquidation(args.symbol))
    elif args.command == "decision" and args.decision_command == "run":
        asyncio.run(_run_decision())
    elif args.command == "decision" and args.decision_command == "test":
        asyncio.run(_test_decision(args.symbol))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: PASS, no failures (network-marked tests excluded by default per `pyproject.toml`)

- [ ] **Step 6: Lint**

Run: `uv run ruff check .`
Expected: no findings (fix any line-length/import-order issues if reported)

- [ ] **Step 7: Commit**

```bash
git add src/hello_coin/cli.py tests/test_cli.py
git commit -m "feat: add liquidation CLI commands and wire into decision engine"
```

---

### Task 13: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the liquidation module to the Architecture section**

In `CLAUDE.md`, after the `src/hello_coin/technical/` architecture block and before
`src/hello_coin/decision/`, insert:

```markdown
`src/hello_coin/liquidation/` is the liquidation-heatmap layer (the 15%-weighted signal, folded
into the decision engine's weighted score alongside whale/technical), see
`docs/superpowers/specs/2026-08-22-liquidation-heatmap-design.md`:

- `models.py` — `LiquidationBucket` (one price level + estimated leveraged value that
  liquidates there) and `LiquidationSnapshot` (a symbol's full heatmap at one point in time).
- `score.py` — pure functions: `compute_liquidation_score()` turns nearby long/short
  liquidation clusters into a `[-1, 1]` bias (or `None`); `nearest_clusters()` returns the
  largest clusters per side as concrete price levels for the decision LLM's entry/exit/
  stop-loss context.
- `coinglass.py` — fetches the heatmap from the Coinglass API (paid key required;
  `is_configured()` checks for it). Response shape is not first-party-confirmed — see the
  design doc's caveat.
- `service.py` — fetches + defensively parses one `LiquidationSnapshot`.
- `storage.py` — SQLite (`data/liquidation.db`, gitignored) with dedup on `(symbol, timestamp)`.
- `scheduler.py` — polls every symbol in `exchange_watch_symbols` every 15 minutes; does not
  run at all if Coinglass isn't configured.
```

- [ ] **Step 2: Update the decision-engine bullet**

Find this line in the `src/hello_coin/decision/` block:

```markdown
- `service.py` — combines both scores (0.7/0.3, never silently re-weighted when one is missing)
  into the LLM prompt and parses the result into a `Decision`.
```

Replace it with:

```markdown
- `service.py` — combines whale/technical/liquidation scores (0.60/0.25/0.15 when all three are
  available; falls back to the original 0.7/0.3 whale/technical split when the liquidation
  signal is missing — never silently re-weighted to anything in between) into the LLM prompt,
  along with the nearest liquidation cluster price levels for entry/exit context, and parses the
  result into a `Decision`.
```

- [ ] **Step 3: Update the Product intent weighting line**

Find this line:

```markdown
- Decision weighting: whale activity ≈ 70%, technical indicators ≈ 30%. Any scoring/decision logic should
  preserve this weighting rather than treating the two signal sources as equal inputs.
```

Replace it with:

```markdown
- Decision weighting: whale activity ≈ 60%, technical indicators ≈ 25%, liquidation heatmap ≈ 15% when
  all three signals are available. When the liquidation signal is unavailable (e.g. Coinglass not
  configured), falls back to whale ≈ 70% / technical ≈ 30% exactly as before — this fallback split
  supersedes the original "always 70/30" wording. Any scoring/decision logic should preserve these
  fixed splits rather than interpolating between them or treating all signal sources as equal inputs.
```

- [ ] **Step 4: Add Coinglass to the paid/freemium key list**

Find this line:

```markdown
  - Paid/freemium key: `cryptoquant.py`, `debank.py`, `nansen.py`, `whale_alert.py`,
    `bitquery.py`. None of these have been smoke-tested against a real key — see
```

Replace it with:

```markdown
  - Paid/freemium key: `cryptoquant.py`, `debank.py`, `nansen.py`, `whale_alert.py`,
    `bitquery.py`, and (in `liquidation/`) `coinglass.py`. None of these have been
    smoke-tested against a real key — see
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the liquidation heatmap integration"
```

---

## Post-plan verification

After all tasks are complete, run the full suite once more to confirm nothing regressed:

```bash
uv run pytest
uv run ruff check .
```

Both should be clean before considering this feature done.
