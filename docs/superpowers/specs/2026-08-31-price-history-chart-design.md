# Price History Chart — design

Date: 2026-08-31

## Problem

The "Market overview" panel shows only the latest close price as a single number (`Close:
79,249.1000`) — there is no way to see how price has moved over time on the dashboard itself,
even though `technical.db` already stores every polled `close_price` per `(symbol, timeframe,
timestamp)`. The project owner wants a line chart of close price alongside the existing
LONG/SHORT skew charts added in
`docs/superpowers/specs/2026-08-31-coin-skew-history-chart-design.md`.

## Where the data comes from

`src/hello_coin/technical/scheduler.py` already polls Binance klines for every symbol in
`exchange_watch_symbols` every 15 minutes and persists a full `IndicatorSnapshot` (including
`close_price`) via `TechnicalStorage.insert_snapshot()`. No new data source, no new fetch cycle —
this is purely a read-and-render addition on top of existing data, the same shape of change as
the skew history chart.

Unlike `whale_events` (73k+ rows, caused the page-load slowdown fixed in the commit right before
this design), `technical_snapshots` is small — currently 40 rows total after 9 days of polling,
one row per symbol per 15 minutes. It won't need pruning at any foreseeable scale, so unlike
`coin_skew_snapshots` there is no retention/prune-on-insert logic in this design. The chart's
30-day lookback window (see below) is a display choice, not a storage constraint.

## Storage changes

`TechnicalStorage` (`src/hello_coin/technical/storage.py`) gains:

- `recent_snapshots(symbol: str, timeframe: str, since: datetime) -> list[dict]` — same dict-per-
  row shape as `latest_snapshot`, ordered by `timestamp` ascending (chart-ready order), filtered
  to `symbol`, `timeframe`, and `timestamp >= since`.
- An index on `(symbol, timeframe, timestamp)`, created in `__init__` alongside the existing
  schema. `latest_snapshot` already matches `symbol`/`timeframe` with plain equality (no `COLLATE
  NOCASE` — the dashboard always passes the canonical `exchange_watch_symbols` string), so a plain
  (non-collated) index matches both `latest_snapshot`'s and the new `recent_snapshots`'s query
  shape. Added now, while the table is still small, specifically because of the lesson from
  today's `whale_events` incident: an unindexed table that's cheap to scan today silently becomes
  a full-scan bottleneck once it grows, and it's free to prevent up front.

## Dashboard wiring

`DashboardSnapshot` (`src/hello_coin/dashboard/models.py`) gains a new field: `price_history:
tuple[dict, ...] = ()`.

`DashboardService.load_snapshot` (`src/hello_coin/dashboard/service.py`) fetches it via
`self._technical_storage.recent_snapshots(symbol, self._timeframe, since=now - timedelta(days=30))`
— the same 30-day window as the skew charts, for consistency across the dashboard rather than
because of any storage constraint (see above).

## Rendering

A `<canvas>` is added to the existing `#market-overview` panel
(`src/hello_coin/dashboard/templates/_panels.html`), right after the existing `Close:` /
`Timeframe:` lines:

```html
<canvas id="price-chart" class="price-chart"
        data-price='{{ snapshot.price_history | tojson }}'></canvas>
```

This reuses the `tojson` Jinja filter already registered in `web.py` for the skew charts — no new
filter needed.

### JS: rename `skew-charts.js` → `charts.js`

`renderPriceChart()` needs the exact same lifecycle as `renderSkewCharts()`: destroy the previous
Chart.js instance before re-creating it, run once on initial page load, and re-run on every htmx
`#panels` swap (`REFRESH_SECONDS` = 60s, per `page.html`). Rather than duplicate that
registry/listener boilerplate in a second file, `skew-charts.js` is renamed to `charts.js` and
gains a second render function, sharing one `charts` instance registry and one `htmx:afterSwap`
listener that calls both `renderSkewCharts()` and `renderPriceChart()`. `page.html`'s script tag
updates from `/static/skew-charts.js` to `/static/charts.js`.

`renderPriceChart()`:
- Reads `#price-chart`'s `data-price` JSON (same parse-with-fallback-to-`[]` pattern as
  `renderSkewCharts()`).
- Skips rendering if the history is empty (matches `renderSkewCharts()`'s behavior for a coin with
  no history yet).
- Draws one line dataset (`close_price` over `timestamp`), styled as a neutral single line (no
  LONG/SHORT semantics, so no green/red — a neutral color, e.g. `#60a5fa`, matching the dashboard's
  existing dark theme rather than introducing a new palette).
- Y-axis is **not** clamped to `[0, 100]` like the skew charts (price is not a percentage) — it
  uses Chart.js's default auto-scaling.

## Testing

- `TechnicalStorage` (`tests/technical/test_storage.py`): `recent_snapshots` filters by symbol,
  timeframe, and `since`, returns ascending order; an `EXPLAIN QUERY PLAN` test (mirroring the one
  just added for `WhaleStorage`) confirms the new index is used rather than a full scan.
- `DashboardService` (`tests/dashboard/test_service.py`): `load_snapshot` populates
  `DashboardSnapshot.price_history` from `TechnicalStorage.recent_snapshots`.
- `web.py` / template (`tests/dashboard/test_web.py`): the rendered page includes `<canvas
  id="price-chart">` with a `data-price` attribute containing the expected JSON-encoded history.
- No JS test changes beyond what already applies to `charts.js` — same as the skew charts, this is
  verified by running the app and checking it in a browser (per `CLAUDE.md`), not a Python test.
