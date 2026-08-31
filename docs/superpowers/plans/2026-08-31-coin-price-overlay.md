# Per-Coin Price Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revert the Market overview price chart, and instead overlay each Hyperdash-watched
coin's own price (from Hyperliquid's `allMids`) directly on that coin's existing LONG/SHORT skew
chart, using a secondary Y axis.

**Architecture:** `HyperdashAdapter.fetch()` gains one extra call per poll to Hyperliquid's
`allMids` endpoint, giving current mid-price for every coin in one request. `SkewSnapshot` gains
a `price` field, carried through the same throttled (5-minute) snapshot pipeline already built
for skew, into the same `coin_skew_snapshots` table (migrated with a new nullable `price`
column). No dashboard-layer code changes are needed — `price` just shows up as one more key in
the JSON already flowing to the template. `charts.js` adds a third dataset (Price, secondary Y
axis) to the existing skew-chart renderer.

**Tech Stack:** Python 3.12, httpx/respx, SQLite, pytest, vanilla JS + already-vendored Chart.js.

Spec: `docs/superpowers/specs/2026-08-31-coin-price-overlay-design.md`

---

### Task 1: Revert the Market overview price chart

**Files:**
- Modify: `src/hello_coin/technical/storage.py`
- Modify: `tests/technical/test_storage.py`
- Modify: `src/hello_coin/dashboard/models.py`
- Modify: `src/hello_coin/dashboard/service.py`
- Modify: `tests/dashboard/test_service.py`
- Modify: `src/hello_coin/dashboard/templates/_panels.html`
- Modify: `src/hello_coin/dashboard/static/dashboard.css`
- Modify: `tests/dashboard/test_web.py`
- Modify: `src/hello_coin/dashboard/static/charts.js`

This is a pure revert of everything built for the Market overview price chart earlier today —
there's no new test to write first; each step below removes code and its matching test, and the
task is verified by the full suite staying green at the end.

- [ ] **Step 1: Remove `recent_snapshots` from `TechnicalStorage`**

In `src/hello_coin/technical/storage.py`, change the imports back to:

```python
import json
import sqlite3
from pathlib import Path

from hello_coin.technical.models import IndicatorSnapshot
```

Delete the `recent_snapshots` method (everything from `def recent_snapshots` to the end of the
file).

- [ ] **Step 2: Remove its tests**

In `tests/technical/test_storage.py`, delete `test_recent_snapshots_uses_an_index_instead_of_scanning_the_table`
and `test_recent_snapshots_filters_by_symbol_timeframe_and_since_ordered_ascending` (everything
from `def test_recent_snapshots_uses_an_index_instead_of_scanning_the_table():` to the end of the
file).

- [ ] **Step 3: Remove `DashboardSnapshot.price_history`**

In `src/hello_coin/dashboard/models.py`, change:

```python
@dataclass(frozen=True)
class DashboardSnapshot:
    symbol: str
    technical: dict[str, Any] | None
    whale_events: tuple[dict[str, Any], ...]
    bias: MarketBias
    source_statuses: tuple[SourceStatus, ...]
    refreshed_at: datetime
    coin_positions: tuple[CoinPositionTable, ...] = ()
    price_history: tuple[dict[str, Any], ...] = ()
```

to:

```python
@dataclass(frozen=True)
class DashboardSnapshot:
    symbol: str
    technical: dict[str, Any] | None
    whale_events: tuple[dict[str, Any], ...]
    bias: MarketBias
    source_statuses: tuple[SourceStatus, ...]
    refreshed_at: datetime
    coin_positions: tuple[CoinPositionTable, ...] = ()
```

- [ ] **Step 4: Remove the price-history wiring from `DashboardService`**

In `src/hello_coin/dashboard/service.py`, change `load_snapshot` from:

```python
        coin_positions = self._load_coin_positions(sources, now)
        activity_symbols = list(dict.fromkeys([asset, *self._hyperdash_watch_coins]))
        # 30 days matches the skew charts' lookback window, for a consistent dashboard feel.
        price_since = now - timedelta(days=30)
        price_history = tuple(
            self._technical_storage.recent_snapshots(symbol, self._timeframe, price_since)
        )
        return DashboardSnapshot(
            symbol=symbol,
            technical=technical,
            whale_events=tuple(self._whale_storage.latest_events(activity_symbols, limit=20)),
            bias=bias,
            source_statuses=tuple(self._source_status(source, now) for source in sources),
            refreshed_at=now,
            coin_positions=coin_positions,
            price_history=price_history,
        )
```

to:

```python
        coin_positions = self._load_coin_positions(sources, now)
        activity_symbols = list(dict.fromkeys([asset, *self._hyperdash_watch_coins]))
        return DashboardSnapshot(
            symbol=symbol,
            technical=technical,
            whale_events=tuple(self._whale_storage.latest_events(activity_symbols, limit=20)),
            bias=bias,
            source_statuses=tuple(self._source_status(source, now) for source in sources),
            refreshed_at=now,
            coin_positions=coin_positions,
        )
```

- [ ] **Step 5: Remove its test**

In `tests/dashboard/test_service.py`, delete `test_load_snapshot_includes_price_history` (from
`def test_load_snapshot_includes_price_history():` to the end of the file).

- [ ] **Step 6: Remove the canvas from the template**

In `src/hello_coin/dashboard/templates/_panels.html`, change:

```html
<div id="market-overview" class="panel">
  <h2>{{ snapshot.symbol }} &middot; Market overview</h2>
  <p>Close: {{ format_number(snapshot.technical.get("close_price") if snapshot.technical else None) }}</p>
  <p>Timeframe: {{ settings.technical_timeframe }}</p>
  <canvas id="price-chart" class="price-chart"
          data-price='{{ snapshot.price_history | tojson }}'></canvas>
</div>
```

to:

```html
<div id="market-overview" class="panel">
  <h2>{{ snapshot.symbol }} &middot; Market overview</h2>
  <p>Close: {{ format_number(snapshot.technical.get("close_price") if snapshot.technical else None) }}</p>
  <p>Timeframe: {{ settings.technical_timeframe }}</p>
</div>
```

- [ ] **Step 7: Remove the CSS rule**

In `src/hello_coin/dashboard/static/dashboard.css`, delete the `.price-chart { ... }` block
(the one directly after `.skew-chart { ... }`):

```css
.price-chart {
  width: 100%;
  max-height: 160px;
  margin-bottom: 0.75rem;
}
```

- [ ] **Step 8: Remove the fixture and test from `test_web.py`**

In `tests/dashboard/test_web.py`, delete the `_PriceHistoryDashboardService` class:

```python
class _PriceHistoryDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        self.calls.append(symbol)
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
            price_history=({
                "symbol": symbol, "timeframe": "1h", "timestamp": now.isoformat(),
                "close_price": 79249.1,
            },),
        )
```

and the `test_panels_renders_price_chart_canvas_with_history_data` test:

```python
def test_panels_renders_price_chart_canvas_with_history_data():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_PriceHistoryDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert 'id="price-chart"' in response.text
    assert 'class="price-chart"' in response.text
    assert "79249.1" in response.text
```

- [ ] **Step 9: Revert `charts.js` to its pre-price-chart state**

Replace the full contents of `src/hello_coin/dashboard/static/charts.js` with:

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

(This is reverted here; Task 6 below adds the new price overlay into `renderSkewCharts()`.)

- [ ] **Step 10: Verify the full suite is green**

Run: `uv run pytest -q`
Expected: all tests pass, no failures (the price-history-chart tests are gone, everything else
unaffected).

Run: `uv run ruff check .`
Expected: no lint errors.

- [ ] **Step 11: Commit**

```bash
git add src/hello_coin/technical/storage.py tests/technical/test_storage.py \
  src/hello_coin/dashboard/models.py src/hello_coin/dashboard/service.py tests/dashboard/test_service.py \
  src/hello_coin/dashboard/templates/_panels.html src/hello_coin/dashboard/static/dashboard.css \
  tests/dashboard/test_web.py src/hello_coin/dashboard/static/charts.js
git commit -m "revert: remove Market overview price chart

Superseded by per-coin price overlays on the skew charts instead —
see docs/superpowers/specs/2026-08-31-coin-price-overlay-design.md."
```

---

### Task 2: `SkewSnapshot.price`

**Files:**
- Modify: `src/hello_coin/ingestion/position_skew.py`
- Test: `tests/ingestion/test_position_skew.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_position_skew.py`:

```python
def test_skew_snapshot_price_defaults_to_none():
    snapshot = SkewSnapshot(
        coin="LINK",
        timestamp=datetime(2026, 8, 31, tzinfo=UTC),
        long_usd=800_000.0,
        short_usd=200_000.0,
        long_pct=0.8,
        short_pct=0.2,
    )

    assert snapshot.price is None


def test_skew_snapshot_accepts_explicit_price():
    snapshot = SkewSnapshot(
        coin="LINK",
        timestamp=datetime(2026, 8, 31, tzinfo=UTC),
        long_usd=800_000.0,
        short_usd=200_000.0,
        long_pct=0.8,
        short_pct=0.2,
        price=10.52,
    )

    assert snapshot.price == 10.52
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v -k price`
Expected: FAIL — `TypeError: SkewSnapshot.__init__() got an unexpected keyword argument 'price'`

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/position_skew.py`, add the field:

```python
@dataclass(frozen=True)
class SkewSnapshot:
    coin: str
    timestamp: datetime
    long_usd: float
    short_usd: float
    long_pct: float
    short_pct: float
    price: float | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_position_skew.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/position_skew.py tests/ingestion/test_position_skew.py
git commit -m "feat: add optional price field to SkewSnapshot"
```

---

### Task 3: Persist `price` in `coin_skew_snapshots`

**Files:**
- Modify: `src/hello_coin/ingestion/storage.py`
- Test: `tests/ingestion/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_storage.py`:

```python
def test_insert_skew_snapshots_persists_and_round_trips_price():
    storage = WhaleStorage(":memory:")
    snapshot = SkewSnapshot(
        "LINK", datetime(2026, 8, 31, tzinfo=UTC), 800_000.0, 200_000.0, 0.8, 0.2, price=10.52
    )

    storage.insert_skew_snapshots([snapshot])

    rows = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert rows[0]["price"] == 10.52


def test_insert_skew_snapshots_stores_none_price_as_null():
    storage = WhaleStorage(":memory:")
    snapshot = _skew_snapshot("LINK", datetime(2026, 8, 31, tzinfo=UTC))  # price defaults to None

    storage.insert_skew_snapshots([snapshot])

    rows = storage.recent_skew_history("LINK", since=datetime(2020, 1, 1, tzinfo=UTC))
    assert rows[0]["price"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_storage.py -v -k round_trips_price`
Expected: FAIL — `KeyError: 'price'` (the column doesn't exist yet, so it's missing from the
returned dict)

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/storage.py`, change `_SKEW_SNAPSHOTS_SCHEMA` to add the nullable
`price` column:

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
    price REAL,
    UNIQUE(coin, timestamp)
)
"""
```

Change `_SKEW_SNAPSHOT_COLUMNS` to include it:

```python
_SKEW_SNAPSHOT_COLUMNS = (
    "coin",
    "timestamp",
    "long_usd",
    "short_usd",
    "long_pct",
    "short_pct",
    "price",
)
```

In `WhaleStorage.__init__`, add a migration for the already-deployed `data/whale.db` (which was
created before this column existed) right after creating the table:

```python
        self._conn.execute(_EVENTS_SCHEMA)
        self._conn.execute(_METRICS_SCHEMA)
        self._conn.execute(_SKEW_SNAPSHOTS_SCHEMA)
        try:
            self._conn.execute("ALTER TABLE coin_skew_snapshots ADD COLUMN price REAL")
        except sqlite3.OperationalError:
            pass  # already migrated, or the table was just created with the column present
        self._conn.execute(_EVENTS_SYMBOL_INDEX)
        self._conn.execute(_METRICS_SYMBOL_INDEX)
        self._conn.execute(_SKEW_SNAPSHOTS_COIN_INDEX)
        self._conn.commit()
```

(No dedicated test is needed for this migration path: every `WhaleStorage(":memory:")` call in
the whole suite exercises `__init__`, so if the `try`/`except` didn't correctly swallow the
"duplicate column" error, every single test in the suite would fail at construction time. The
full suite passing at the end of this task is the proof.)

Update `insert_skew_snapshots` to write `price`:

```python
    def insert_skew_snapshots(self, snapshots: list[SkewSnapshot]) -> int:
        inserted = 0
        for snapshot in snapshots:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO coin_skew_snapshots
                    (coin, timestamp, long_usd, short_usd, long_pct, short_pct, price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.coin,
                    snapshot.timestamp.isoformat(),
                    snapshot.long_usd,
                    snapshot.short_usd,
                    snapshot.long_pct,
                    snapshot.short_pct,
                    snapshot.price,
                ),
            )
            inserted += cursor.rowcount
        if snapshots:
            cutoff = max(snapshot.timestamp for snapshot in snapshots) - timedelta(days=30)
            self._conn.execute(
                "DELETE FROM coin_skew_snapshots WHERE timestamp < ?", (cutoff.isoformat(),)
            )
        self._conn.commit()
        return inserted
```

Update `recent_skew_history` to read `price`:

```python
    def recent_skew_history(self, coin: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT coin, timestamp, long_usd, short_usd, long_pct, short_pct, price
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
git commit -m "feat: persist coin price alongside skew snapshots"
```

---

### Task 4: Fetch price from Hyperliquid's `allMids` in `HyperdashAdapter`

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/hyperdash.py`
- Test: `tests/ingestion/test_hyperdash.py`

- [ ] **Step 1: Write the failing tests**

First, update the three existing direct `_update_skew(...)` calls in
`tests/ingestion/test_hyperdash.py` to pass an empty `prices` dict as the new third argument —
`_update_skew`'s signature is about to gain a required `prices` parameter:

In `test_update_skew_queues_snapshot_for_every_watched_coin_including_zero_positions`, change:

```python
    adapter._update_skew({}, now)
```

to:

```python
    adapter._update_skew({}, now, {})
```

In `test_update_skew_throttles_snapshots_within_five_minutes`, change both calls:

```python
    adapter._update_skew({("0xabc", "LINK"): event}, now)
    adapter.consume_skew_snapshots()

    adapter._update_skew({("0xabc", "LINK"): event}, now + timedelta(minutes=4))
```

to:

```python
    adapter._update_skew({("0xabc", "LINK"): event}, now, {})
    adapter.consume_skew_snapshots()

    adapter._update_skew({("0xabc", "LINK"): event}, now + timedelta(minutes=4), {})
```

In `test_update_skew_emits_new_snapshot_after_five_minutes`, change both calls:

```python
    adapter._update_skew({("0xabc", "LINK"): event}, now)
    adapter.consume_skew_snapshots()

    later = now + timedelta(minutes=5)
    adapter._update_skew({("0xabc", "LINK"): event}, later)
```

to:

```python
    adapter._update_skew({("0xabc", "LINK"): event}, now, {})
    adapter.consume_skew_snapshots()

    later = now + timedelta(minutes=5)
    adapter._update_skew({("0xabc", "LINK"): event}, later, {})
```

Then append new tests to the end of the file:

```python
def test_update_skew_attaches_price_from_prices_dict():
    adapter = _adapter(coins=["LINK", "SOL"])
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)

    adapter._update_skew({}, now, {"LINK": 10.52})

    snapshots = {snapshot.coin: snapshot for snapshot in adapter.consume_skew_snapshots()}
    assert snapshots["LINK"].price == 10.52
    assert snapshots["SOL"].price is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_attaches_price_from_hyperliquid_all_mids():
    wallet = "0x8888888888888888888888888888888888888888"
    respx.post(HYPERDASH_GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 800_000}]}}}
        )
    )

    def hyperliquid_router(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("type") == "allMids":
            return httpx.Response(200, json={"LINK": "10.52"})
        return httpx.Response(200, json={
            "assetPositions": [{"position": {"coin": "LINK", "szi": "10", "positionValue": "800000"}}]
        })

    respx.post(HYPERLIQUID_INFO_URL).mock(side_effect=hyperliquid_router)
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    await adapter.fetch()

    snapshots = adapter.consume_skew_snapshots()
    assert snapshots[0].price == 10.52


@pytest.mark.asyncio
@respx.mock
async def test_fetch_leaves_price_none_when_all_mids_request_fails():
    wallet = "0x9999999999999999999999999999999999999999"
    respx.post(HYPERDASH_GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"perpDeltas": {"deltas": [{"address": wallet, "current": 800_000}]}}}
        )
    )

    def hyperliquid_router(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("type") == "allMids":
            return httpx.Response(500)
        return httpx.Response(200, json={
            "assetPositions": [{"position": {"coin": "LINK", "szi": "10", "positionValue": "800000"}}]
        })

    respx.post(HYPERLIQUID_INFO_URL).mock(side_effect=hyperliquid_router)
    adapter = HyperdashAdapter(
        Settings(_env_file=None, hyperdash_api_token="token", hyperdash_watch_coins=["LINK"])
    )

    events = await adapter.fetch()

    assert len(events) == 1  # position events still produced despite allMids failing
    snapshots = adapter.consume_skew_snapshots()
    assert snapshots[0].price is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v`
Expected: FAIL — the three updated `_update_skew` calls now raise `TypeError: _update_skew()
takes 3 positional arguments but 4 were given` (signature doesn't accept `prices` yet), and the
three new tests fail similarly / on missing `.price` attachment.

- [ ] **Step 3: Implement**

In `src/hello_coin/ingestion/adapters/hyperdash.py`, in `fetch()`, add the `allMids` call right
after the wallet-position loop and before `self._update_skew(observed, now)`:

```python
            prices: dict[str, float] = {}
            try:
                response = await client.post(HYPERLIQUID_INFO_URL, json={"type": "allMids"})
                response.raise_for_status()
                for coin, value in response.json().items():
                    parsed = _number(value)
                    if parsed is not None:
                        prices[str(coin).upper()] = parsed
            except (httpx.HTTPError, AttributeError, TypeError, ValueError):
                pass

            self._update_skew(observed, now, prices)
```

(This replaces the existing `self._update_skew(observed, now)` line — same call, with the new
`prices` argument added ahead of it. It's deliberately independent of `coin_statuses`: a failed
`allMids` call doesn't mark any coin as `ERROR`, since that state is reserved for failures in the
adapter's core whale-tracking responsibilities, not this best-effort price enrichment.)

Update `_update_skew`'s signature and body to accept and use `prices`:

```python
    def _update_skew(
        self,
        observed: dict[tuple[str, str], WhaleEvent],
        now: datetime,
        prices: dict[str, float],
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
                    SkewSnapshot(
                        coin, now, long_usd, short_usd, long_pct, short_pct, prices.get(coin)
                    )
                )
                self._last_skew_snapshot_at[coin] = now
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_hyperdash.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py
git commit -m "feat: fetch coin price from Hyperliquid allMids"
```

---

### Task 5: Overlay price on the skew charts in the browser

**Files:**
- Modify: `src/hello_coin/dashboard/static/charts.js`
- Modify: `tests/dashboard/test_web.py`

- [ ] **Step 1: Write the failing test**

In `tests/dashboard/test_web.py`, add a `"price"` key to `_CoinDashboardService`'s LINK
`skew_history` row:

```python
                    skew_history=({
                        "coin": "LINK", "timestamp": now.isoformat(), "long_usd": 800_000.0,
                        "short_usd": 200_000.0, "long_pct": 0.8, "short_pct": 0.2,
                        "price": 10.52,
                    },),
```

Extend `test_panels_renders_skew_chart_canvas_with_history_data` to assert the price value is in
the rendered JSON:

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
    assert "10.52" in response.text
```

- [ ] **Step 2: Run the test — expect it to already pass**

`CoinPositionTable.skew_history` is passed through `| tojson` as an opaque dict, with no
dashboard-layer code touching individual keys — so unlike a normal TDD red step, this test should
already pass from the Step 1 fixture edit alone, with no implementation step needed.

Run: `uv run pytest tests/dashboard/test_web.py -v -k skew_chart_canvas`
Expected: PASS. If it instead fails with `assert "10.52" in response.text`, something *is*
stripping unknown keys somewhere in the pipeline — stop and investigate that as a bug before
continuing to Step 4.

- [ ] **Step 3: Run the full file to confirm nothing else broke**

Run: `uv run pytest tests/dashboard/test_web.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 4: Add the price dataset to `renderSkewCharts()`**

In `src/hello_coin/dashboard/static/charts.js`, replace the `datasets` array and `options` block
inside `renderSkewCharts()`:

```javascript
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
            {
              label: "Price",
              data: history.map(function (row) { return row.price; }),
              borderColor: "#60a5fa",
              backgroundColor: "#60a5fa",
              pointRadius: 0,
              borderWidth: 1.5,
              yAxisID: "y1",
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
            y1: {
              position: "right",
              grid: { drawOnChartArea: false },
            },
          },
          plugins: { legend: { labels: { boxWidth: 10 } } },
        },
      });
```

(A `null` `price` — a snapshot taken before this feature shipped, or a cycle where `allMids`
failed — simply leaves a gap in the Price line; Chart.js's default behavior for `null` data
points. `y1` has no `min`/`max`, so it auto-scales to whatever price range that coin's history
covers. `grid: { drawOnChartArea: false }` stops the secondary axis's gridlines from drawing over
the primary one.)

- [ ] **Step 5: Verify in the browser**

Rebuild and restart the Docker container:

```bash
docker compose up -d --build
```

Wait a few poll cycles (`HyperdashAdapter` polls every 60s, but the skew snapshot throttle is 5
minutes — so it takes up to 5 minutes for the *first* snapshot with a real price to land), then
open `http://localhost:8080` and confirm:
- Each coin panel's skew chart now shows a third "Price" line in the legend, plotted against a
  right-hand Y axis with its own auto-scaled range.
- Existing LONG %/SHORT % lines and their left-hand 0–100% axis are unaffected.
- No JS console errors.
- Waiting for one htmx auto-refresh cycle doesn't break or duplicate any chart.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/dashboard/static/charts.js tests/dashboard/test_web.py
git commit -m "feat: overlay coin price on skew charts with a secondary Y axis"
```

---

### Task 6: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass, no failures or errors.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check .`
Expected: no lint errors.

- [ ] **Step 3: Confirm the dashboard is rebuilt and running**

If Task 5's Step 5 wasn't the most recent Docker rebuild, rebuild again:

```bash
docker compose up -d --build
```

Confirm `http://localhost:8080` loads without errors, the Market overview panel no longer shows
a price chart, and every coin panel's skew chart shows LONG %, SHORT %, and (once enough poll
cycles have passed) Price, on two Y axes.
