# Per-Coin Price Overlay on Skew Charts — design

Date: 2026-08-31

## Problem

`docs/superpowers/specs/2026-08-31-price-history-chart-design.md` added a close-price chart to
the dashboard's "Market overview" panel, sourced from `technical.db` (Binance klines for whichever
symbol is selected in the dropdown). After seeing it, the project owner wants something different:
a price line for **every Hyperdash-watched coin** (`LINK`, `SOL`, `SUI`, `NEAR`, `HYPE`, `BTC`),
overlaid directly on that coin's existing LONG/SHORT skew chart — not a single chart for whichever
symbol happens to be selected.

**This design supersedes the Market overview price chart, which is removed.** `technical.db`
only tracks `exchange_watch_symbols` (Binance pairs), and there's no guarantee every
Hyperdash-watched coin has a matching, liquid Binance pair — `HYPE` in particular is Hyperliquid's
own token and may not be listed elsewhere. Sourcing price from Hyperliquid itself, the same
exchange the whale position data already comes from, sidesteps that mapping risk entirely and
needs no new per-coin poller.

## Removed

The price-history-chart work is reverted in full — implemented earlier today, but superseded
before anyone other than the project owner saw it:

- `TechnicalStorage.recent_snapshots()` (`src/hello_coin/technical/storage.py`) — deleted, along
  with its now-unused `datetime` import.
- `tests/technical/test_storage.py`'s two `recent_snapshots` tests — deleted.
- `DashboardSnapshot.price_history` (`src/hello_coin/dashboard/models.py`) — deleted.
- The `price_since`/`price_history` computation and `price_history=` kwarg in
  `DashboardService.load_snapshot` (`src/hello_coin/dashboard/service.py`) — deleted.
- `tests/dashboard/test_service.py`'s `test_load_snapshot_includes_price_history` — deleted.
- The `<canvas id="price-chart">` element in the `#market-overview` panel
  (`src/hello_coin/dashboard/templates/_panels.html`) — deleted.
- The `.price-chart` rule in `src/hello_coin/dashboard/static/dashboard.css` — deleted.
- `_PriceHistoryDashboardService` and `test_panels_renders_price_chart_canvas_with_history_data`
  in `tests/dashboard/test_web.py` — deleted.
- `renderPriceChart()` in `src/hello_coin/dashboard/static/charts.js`, and its two call sites
  (initial render, `htmx:afterSwap`) — deleted. `renderSkewCharts()` stays, and is extended below.
- `page.html` needs no changes — it still loads `chart.min.js` and `charts.js` for the (modified)
  skew charts.

## Where the price comes from

`HyperdashAdapter.fetch()` already holds an open `httpx.AsyncClient` and already talks to
`HYPERLIQUID_INFO_URL` (`https://api.hyperliquid.xyz/info`) once per wallet to fetch
`clearinghouseState`. It gains one more call per poll cycle — not per wallet, once total — to
Hyperliquid's `allMids` endpoint:

```python
response = await client.post(HYPERLIQUID_INFO_URL, json={"type": "allMids"})
response.raise_for_status()
mids = response.json()  # {"BTC": "97123.5", "LINK": "10.52", ...}
```

This returns the current mid price for every coin Hyperliquid trades, in one request — exactly
what's needed for all `hyperdash_watch_coins` at once, with no per-coin symbol mapping.

This call is **best-effort and independent of the adapter's core responsibilities**: if it fails
(network error, bad JSON), the whole poll is not aborted, `coin_statuses` is not touched (that's
reserved for the GraphQL-delta and position-state failures that are actually core to whale
tracking), and every coin simply gets `price=None` for that cycle — consistent with the "`None`
means not available, never fabricated" convention already used for `IndicatorSnapshot` fields.
Prices are looked up by uppercased coin symbol (matching the existing `configured_coin.upper()`
normalization used throughout `_update_skew`).

## Data model and storage

`SkewSnapshot` (`src/hello_coin/ingestion/position_skew.py`) gains a fifth field, appended last
with a default so every existing positional construction across the test suite keeps working
unchanged:

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

`_update_skew()` gains a third parameter, `prices: dict[str, float]`, and passes
`prices.get(coin)` into each `SkewSnapshot` it builds. This reuses the exact throttle (once per 5
minutes per coin) and queue (`_pending_skew_snapshots` / `consume_skew_snapshots()`) already
built for skew — price is just one more field sampled at the same cadence, not a separate
pipeline.

`coin_skew_snapshots` (`WhaleStorage`, `src/hello_coin/ingestion/storage.py`) gains a nullable
`price REAL` column:

```sql
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
```

Putting `price` in the `CREATE TABLE` DDL only helps *new* databases (a fresh `:memory:` in
tests, or a from-scratch `data/whale.db`) — `CREATE TABLE IF NOT EXISTS` is a no-op against the
already-deployed `data/whale.db`, which was created earlier today without this column. So
`WhaleStorage.__init__` also runs an idempotent migration right after creating the table:

```python
try:
    self._conn.execute("ALTER TABLE coin_skew_snapshots ADD COLUMN price REAL")
except sqlite3.OperationalError:
    pass  # already migrated (or the table was just created with the column already present)
```

The `try`/`except` makes this safe to run on every startup regardless of which case applies:
a pre-existing database gets the column added once; a brand-new database (which already has the
column from the `CREATE TABLE` above) hits "duplicate column name" and is silently skipped.
Existing rows get `price = NULL` — correctly represented as "not sampled," not fabricated as 0.

`insert_skew_snapshots()` and `recent_skew_history()` both add `price` to their column lists
(insert values and `SELECT`, respectively), and `_SKEW_SNAPSHOT_COLUMNS` gains `"price"` at the
end.

## Dashboard wiring

None needed. `CoinPositionTable.skew_history` and the `_panels.html` template already pass
`table.skew_history` through `| tojson` as opaque dicts — the new `price` key shows up in the
JSON automatically, without touching `dashboard/models.py`, `dashboard/service.py`, or the
template.

## Rendering

`renderSkewCharts()` (`src/hello_coin/dashboard/static/charts.js`) gains a third dataset drawn on
a secondary Y axis, since price and percentage are different units on wildly different scales:

```javascript
{
  label: "Price",
  data: history.map(function (row) { return row.price; }),
  borderColor: "#60a5fa",
  backgroundColor: "#60a5fa",
  pointRadius: 0,
  borderWidth: 1.5,
  yAxisID: "y1",
}
```

and the chart's `scales` config gains the matching axis:

```javascript
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
}
```

`y1` has no `min`/`max` — it auto-scales to whatever price range that coin's history covers.
`grid: { drawOnChartArea: false }` keeps the secondary axis from drawing its own gridlines over
the primary one, standard practice for a dual-axis Chart.js chart. A `null` `price` (not yet
sampled under the new column, or a cycle where `allMids` failed) simply leaves a gap in the Price
line — Chart.js's default behavior for `null` data points — rather than interpolating a fake
value.

## Testing

- `position_skew.py` (`tests/ingestion/test_position_skew.py`): `SkewSnapshot` accepts and
  defaults `price` correctly (construction test only, same as the original field additions).
- `HyperdashAdapter` (`tests/ingestion/test_hyperdash.py`): `_update_skew(observed, now, prices)`
  attaches the matching price per coin from the `prices` dict, and defaults to `None` for a coin
  missing from it (simulating a partial or failed `allMids` response). `fetch()` itself gets one
  `respx`-mocked test confirming it calls `allMids` and that a failure there doesn't prevent
  events/alerts/snapshots from being produced (mirroring the existing "isolates ... failure"
  tests for the GraphQL/position calls).
- `WhaleStorage` (`tests/ingestion/test_storage.py`): `insert_skew_snapshots` persists and
  round-trips `price` (including `None`); a fresh `:memory:` database's migration `ALTER TABLE`
  is a safe no-op (covered implicitly — every existing `WhaleStorage(":memory:")` test already
  exercises `__init__`, so this doesn't need a dedicated test beyond confirming `price` round-trips
  correctly on a freshly-constructed instance).
- `scheduler.py` (`tests/ingestion/test_scheduler.py`): unaffected — `poll_once` just forwards
  whatever `consume_skew_snapshots()` returns to `insert_skew_snapshots`, and `SkewSnapshot`'s new
  field has a default, so the existing fixture continues to work unchanged.
- `web.py` / template (`tests/dashboard/test_web.py`): the existing skew-chart test
  (`test_panels_renders_skew_chart_canvas_with_history_data`) gets its fixture's `skew_history`
  row extended with a `"price"` key, and the test additionally asserts that value appears in the
  rendered `data-skew` JSON — confirming the price key flows through the existing `tojson`
  pipeline without any dashboard-layer code changes.
- No JS test changes beyond what already applies to `charts.js`: verified by running the app and
  checking it in a browser (per `CLAUDE.md`), not a Python test.
