# Price History Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chart close price over the last 30 days on the dashboard's "Market overview" panel,
using the `close_price` already polled into `technical.db` every 15 minutes.

**Architecture:** `TechnicalStorage` gains a ranged read (`recent_snapshots`) mirroring the
existing `latest_snapshot`, plus an index so the read stays fast as the table grows.
`DashboardService` loads the last 30 days into a new `DashboardSnapshot.price_history` field. The
template renders it into a `<canvas>` inside the existing `#market-overview` panel, reusing the
`tojson` filter already registered for the skew charts. `skew-charts.js` is renamed to
`charts.js` and gains a second render function, sharing the destroy-and-redraw lifecycle and the
`htmx:afterSwap` listener already built for the skew charts.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 (via Starlette), SQLite, pytest, vanilla JS +
already-vendored Chart.js (no new dependency).

Spec: `docs/superpowers/specs/2026-08-31-price-history-chart-design.md`

---

### Task 1: `TechnicalStorage.recent_snapshots` and index

**Files:**
- Modify: `src/hello_coin/technical/storage.py`
- Test: `tests/technical/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/technical/test_storage.py`:

```python
def test_recent_snapshots_uses_an_index_instead_of_scanning_the_table():
    storage = TechnicalStorage(":memory:")

    plan = storage._conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT * FROM technical_snapshots WHERE symbol = 'BTCUSDT' AND timeframe = '1h' "
        "AND timestamp >= '2026-01-01'"
    ).fetchall()

    assert any("USING INDEX" in str(step) for step in plan)


def test_recent_snapshots_filters_by_symbol_timeframe_and_since_ordered_ascending():
    storage = TechnicalStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))
    storage.insert_snapshot(
        IndicatorSnapshot(
            symbol="BTCUSDT",
            timeframe="4h",
            timestamp=datetime(2026, 8, 22, 1, tzinfo=UTC),
            close_price=200.0,
            rsi=None,
            macd_line=None,
            macd_signal=None,
            macd_histogram=None,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            ema=None,
            atr=None,
        )
    )

    rows = storage.recent_snapshots("BTCUSDT", "1h", since=datetime(2026, 8, 21, tzinfo=UTC))

    assert [row["timestamp"] for row in rows] == [
        "2026-08-22T00:00:00+00:00",
        "2026-08-22T01:00:00+00:00",
    ]
```

`IndicatorSnapshot` is already imported at the top of this file — no import changes are needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/technical/test_storage.py -v -k recent_snapshots`
Expected: FAIL — `AttributeError: 'TechnicalStorage' object has no attribute 'recent_snapshots'`

- [ ] **Step 3: Implement**

In `src/hello_coin/technical/storage.py`, add a new index constant after `_SCHEMA`:

```python
_SYMBOL_TIMEFRAME_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_technical_snapshots_symbol_timeframe_timestamp "
    "ON technical_snapshots(symbol, timeframe, timestamp)"
)
```

In `TechnicalStorage.__init__`, add the index alongside the existing schema:

```python
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.execute(_SYMBOL_TIMEFRAME_INDEX)
        self._conn.commit()
```

Add the new method at the end of the class (after `latest_snapshot`):

```python
    def recent_snapshots(self, symbol: str, timeframe: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT symbol, timeframe, timestamp, close_price, rsi, macd_line, macd_signal,
                   macd_histogram, bb_upper, bb_middle, bb_lower, ema, atr, raw
            FROM technical_snapshots
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (symbol, timeframe, since.isoformat()),
        ).fetchall()
        columns = (
            "symbol",
            "timeframe",
            "timestamp",
            "close_price",
            "rsi",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "ema",
            "atr",
            "raw",
        )
        return [dict(zip(columns, row, strict=True)) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/technical/test_storage.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/storage.py tests/technical/test_storage.py
git commit -m "feat: add indexed recent_snapshots range query to TechnicalStorage"
```

---

### Task 2: `DashboardSnapshot.price_history` and `DashboardService` wiring

**Files:**
- Modify: `src/hello_coin/dashboard/models.py`
- Modify: `src/hello_coin/dashboard/service.py`
- Test: `tests/dashboard/test_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/dashboard/test_service.py`:

```python
def test_load_snapshot_includes_price_history():
    service, whale_storage, technical_storage = _service()
    technical_storage.insert_snapshot(_technical_snapshot())
    technical_storage.insert_snapshot(
        IndicatorSnapshot(
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp=NOW - timedelta(hours=1),
            close_price=90.0,
            rsi=None,
            macd_line=None,
            macd_signal=None,
            macd_histogram=None,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            ema=None,
            atr=None,
        )
    )

    snapshot = service.load_snapshot("BTCUSDT", [], now=NOW)

    assert [row["close_price"] for row in snapshot.price_history] == [90.0, 100.0]
```

(`IndicatorSnapshot` is already imported at the top of this file — no import changes needed.
`_technical_snapshot()` returns a snapshot at `NOW` with `close_price=100.0`, `timeframe="1h"` —
see the existing helper near the top of the file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dashboard/test_service.py -v -k price_history`
Expected: FAIL — `AttributeError: 'DashboardSnapshot' object has no attribute 'price_history'`

- [ ] **Step 3: Implement**

In `src/hello_coin/dashboard/models.py`, add a new field to `DashboardSnapshot`:

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

In `src/hello_coin/dashboard/service.py`, update `load_snapshot` to fetch and attach the price
history:

```python
    def load_snapshot(
        self, symbol: str, sources: Sequence[Adapter], now: datetime
    ) -> DashboardSnapshot:
        asset = base_asset(symbol)
        since = now - timedelta(hours=self._lookback_hours)
        events = self._whale_storage.recent_events(asset, since)
        metrics = self._whale_storage.recent_metrics(symbol, since)
        metrics += self._whale_storage.recent_metrics(asset, since)
        technical = self._technical_storage.latest_snapshot(symbol, self._timeframe)
        technical_score = compute_technical_score(technical) if technical is not None else None
        bias = compute_market_bias(compute_whale_score(events, metrics), technical_score)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_service.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/dashboard/models.py src/hello_coin/dashboard/service.py tests/dashboard/test_service.py
git commit -m "feat: load price history into DashboardService snapshots"
```

---

### Task 3: Render the price chart canvas in the dashboard template

**Files:**
- Modify: `src/hello_coin/dashboard/templates/_panels.html`
- Modify: `src/hello_coin/dashboard/static/dashboard.css`
- Test: `tests/dashboard/test_web.py`

- [ ] **Step 1: Write the failing test**

In `tests/dashboard/test_web.py`, add a new fixture class after `_CoinDashboardService` (or
anywhere alongside the other `_DashboardService` subclasses):

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

Append a new test:

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_web.py -v -k price_chart`
Expected: FAIL — `assert 'id="price-chart"' in response.text` fails (canvas doesn't exist yet)

- [ ] **Step 3: Implement**

In `src/hello_coin/dashboard/templates/_panels.html`, add a `<canvas>` to the `#market-overview`
panel:

```html
<div id="market-overview" class="panel">
  <h2>{{ snapshot.symbol }} &middot; Market overview</h2>
  <p>Close: {{ format_number(snapshot.technical.get("close_price") if snapshot.technical else None) }}</p>
  <p>Timeframe: {{ settings.technical_timeframe }}</p>
  <canvas id="price-chart" class="price-chart"
          data-price='{{ snapshot.price_history | tojson }}'></canvas>
</div>
```

(The `tojson` filter is already registered in `web.py` from the skew-chart work — no changes
needed there.)

In `src/hello_coin/dashboard/static/dashboard.css`, add a new rule after the `.skew-chart { ... }`
block:

```css
.price-chart {
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
git add src/hello_coin/dashboard/templates/_panels.html src/hello_coin/dashboard/static/dashboard.css tests/dashboard/test_web.py
git commit -m "feat: render price history canvas in the market overview panel"
```

---

### Task 4: Draw the price chart in the browser

**Files:**
- Rename: `src/hello_coin/dashboard/static/skew-charts.js` → `src/hello_coin/dashboard/static/charts.js`
- Modify: `src/hello_coin/dashboard/templates/page.html`

No Python test here — same as the skew chart's browser JS, this is verified by running the app
and checking it in a browser (per `CLAUDE.md`), not a Python test.

- [ ] **Step 1: Rename and update `skew-charts.js` → `charts.js`**

```bash
git mv src/hello_coin/dashboard/static/skew-charts.js src/hello_coin/dashboard/static/charts.js
```

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

  function renderPriceChart() {
    var canvas = document.getElementById("price-chart");
    if (!canvas) {
      return;
    }
    var existing = charts[canvas.id];
    if (existing) {
      existing.destroy();
      delete charts[canvas.id];
    }
    var history;
    try {
      history = JSON.parse(canvas.dataset.price || "[]");
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
            label: "Close",
            data: history.map(function (row) { return row.close_price; }),
            borderColor: "#60a5fa",
            backgroundColor: "#60a5fa",
            pointRadius: 0,
            borderWidth: 1.5,
          },
        ],
      },
      options: {
        animation: false,
        scales: {
          x: { display: false },
        },
        plugins: { legend: { labels: { boxWidth: 10 } } },
      },
    });
  }

  renderSkewCharts();
  renderPriceChart();

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "panels") {
      renderSkewCharts();
      renderPriceChart();
    }
  });
})();
```

- [ ] **Step 2: Update the script tag in `page.html`**

In `src/hello_coin/dashboard/templates/page.html`, change:

```html
  <script src="/static/dashboard.js"></script>
  <script src="/static/skew-charts.js"></script>
</body>
```

to:

```html
  <script src="/static/dashboard.js"></script>
  <script src="/static/charts.js"></script>
</body>
```

- [ ] **Step 3: Verify in the browser**

Rebuild and restart the Docker container so the running dashboard reflects these changes:

```bash
docker compose up -d --build
```

Then open `http://localhost:8080` and confirm:
- The "Market overview" panel shows a blue "Close" line chart under the `Close:` / `Timeframe:`
  text (once `technical.db` has more than one snapshot for the selected symbol — on a fresh
  deploy with only one or zero stored snapshots, the canvas will be empty, which is expected).
- The coin panels' LONG %/SHORT % charts still render exactly as before (renaming the file must
  not have broken `renderSkewCharts()`).
- No JS console errors (`Chart is not defined`, `charts.js` 404, etc.).
- Waiting for one htmx auto-refresh cycle doesn't break either chart or duplicate it.

- [ ] **Step 4: Commit**

```bash
git add src/hello_coin/dashboard/static/charts.js src/hello_coin/dashboard/templates/page.html
git commit -m "feat: chart price history alongside skew charts"
```

(`git mv` already staged the rename; this `git add` on the new path additionally stages the
content edit made to it in Step 1.)

---

### Task 5: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass, no failures or errors.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check .`
Expected: no lint errors.

- [ ] **Step 3: Confirm the dashboard is rebuilt and running**

If Task 4's Step 3 wasn't the most recent Docker rebuild, rebuild again:

```bash
docker compose up -d --build
```

Confirm `http://localhost:8080` loads without errors, the Market overview panel renders a
`#price-chart` canvas, and the existing coin skew charts are unaffected.
