# Coin LONG/SHORT Skew History Chart — design

Date: 2026-08-31

## Problem

The dashboard already shows each coin panel's current LONG/SHORT dominance
(`formatting.coin_skew`, e.g. "LONG 82%"), computed live from Hyperdash position rows on every
page refresh. That percentage is never persisted — there is no way to see how a coin's skew has
moved over time. The project owner wants a snapshot of each watched coin's long/short percentage
saved once every 5 minutes, kept for 30 days, and charted directly inside that coin's existing
panel.

## Where to sample from

`HyperdashAdapter._update_skew()` already computes `(long_usd, short_usd)` totals per coin on
every poll (every `poll_interval_seconds` = 60s), feeding them to `SkewTracker` for the existing
Telegram dominance alerts. This is exactly the data a history snapshot needs — no new query
against `whale.db` and no new fetch cycle.

Sampling is throttled to once per 5 minutes per coin, tracked in-memory in the adapter
(`_last_skew_snapshot_at: dict[str, datetime]`), independent of the alert/hysteresis state
machine. Snapshots are queued the same way `SkewAlert`s already are
(`_pending_skew_snapshots: list[SkewSnapshot]`, drained via a new `consume_skew_snapshots()`),
and `scheduler.poll_once()` persists them to storage right after handling alerts.

This mirrors the existing `SkewAlert` plumbing on purpose, and deliberately does *not* sample from
the dashboard's own request/response cycle: the ingestion service (`hello-coin ingest run`) can
run standalone without the dashboard, and history must keep accumulating either way.

## Data model and storage

New table in `data/whale.db` (via `WhaleStorage`, following the existing `whale_events` /
`whale_metrics` pattern):

```sql
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
```

`src/hello_coin/ingestion/position_skew.py` gains:

- `SNAPSHOT_INTERVAL_SECONDS = 300`
- `@dataclass(frozen=True) class SkewSnapshot`: `coin`, `timestamp`, `long_usd`, `short_usd`,
  `long_pct`, `short_pct`

`WhaleStorage` gains:

- `insert_skew_snapshots(snapshots: list[SkewSnapshot]) -> int` — insert-or-ignore per row
  (dedup on `(coin, timestamp)`, matching the throttle already preventing sub-5-minute rows).
  When `snapshots` is non-empty, also deletes any row with `timestamp` older than 30 days before
  the batch's own latest timestamp (`max(s.timestamp for s in snapshots) - 30 days`). Deriving
  the cutoff from the batch itself (instead of calling `datetime.now()` inside storage) keeps the
  method deterministic and testable, and pruning naturally happens on every adapter poll cycle
  that has fresh data — no separate cleanup job needed.
- `recent_skew_history(coin: str, since: datetime) -> list[dict]` — rows for one coin, ordered by
  `timestamp` ascending (chart-ready order), same dict-per-row shape as `recent_events`.

## Adapter changes

`HyperdashAdapter.__init__` adds `self._last_skew_snapshot_at: dict[str, datetime] = {}` and
`self._pending_skew_snapshots: list[SkewSnapshot] = []`.

`_update_skew` takes the poll's `now` (already computed at the top of `fetch()`) as a second
parameter. After updating `SkewTracker` for a coin, it also checks the throttle:

```python
last = self._last_skew_snapshot_at.get(coin)
if last is None or (now - last).total_seconds() >= SNAPSHOT_INTERVAL_SECONDS:
    long_pct, short_pct = compute_skew(long_usd, short_usd)
    self._pending_skew_snapshots.append(SkewSnapshot(coin, now, long_usd, short_usd, long_pct, short_pct))
    self._last_skew_snapshot_at[coin] = now
```

A coin with zero tracked positions still gets a `(0.0, 0.0)` snapshot every 5 minutes (same
"no data is still a data point" reasoning as the existing alert logic) — the chart should show
skew dropping to 0% when whales exit, not a gap.

New `consume_skew_snapshots(self) -> list[SkewSnapshot]` drains and clears the pending list, same
shape as `consume_skew_alerts()`.

`Adapter` base class gets a default `consume_skew_snapshots() -> list[SkewSnapshot]` returning
`[]`, alongside the existing `consume_skew_alerts()` default.

## Scheduler changes

`scheduler.poll_once()` calls `storage.insert_skew_snapshots(adapter.consume_skew_snapshots())`
right after the existing alert-notification block (order doesn't matter functionally, but keeping
alerts first preserves today's log/behavior ordering).

## Dashboard changes

`CoinPositionTable` (`dashboard/models.py`) gains a fourth field: `skew_history: tuple[dict, ...]
= ()`.

`DashboardService._load_coin_positions` fetches each coin's history via
`self._whale_storage.recent_skew_history(coin, since=now - timedelta(days=30))` and stores it on
the `CoinPositionTable`. This reuses the same `WhaleStorage` instance already injected into
`DashboardService` — no new storage wiring.

Rendering: each coin panel gets a `<canvas>` holding two lines (`long_pct`, `short_pct`) over
time, drawn with Chart.js. Following the project's existing convention of vendoring JS assets
locally (`static/htmx.min.js`) rather than pulling from a CDN, Chart.js's UMD build is vendored
to `static/chart.min.js` and loaded once in `page.html`.

The chart's data is embedded as JSON on the canvas element:

```html
<canvas id="{{ coin_panel_id(table.coin) }}-skew-chart" class="skew-chart"
        data-skew='{{ table.skew_history | tojson }}'></canvas>
```

Jinja2 (via Starlette's `Jinja2Templates`, unlike Flask) does not register a `tojson` filter by
default — `web.py` adds one: `templates.env.filters["tojson"] = json.dumps`.

A new `static/skew-charts.js` reads every `canvas.skew-chart` on the page, parses its `data-skew`
JSON, and (re)draws a Chart.js line chart into it. Because the whole `#panels` element is replaced
wholesale by htmx every `refresh_seconds` (see `page.html`'s `hx-swap="innerHTML"`), any existing
Chart.js instances tied to the old canvases are destroyed and this function re-runs on both
`DOMContentLoaded` and the existing `htmx:afterSwap` event (the same event `dashboard.js` already
listens to for the refresh countdown), keyed off the same `event.detail.target.id === "panels"`
check.

No date-range picker or zoom control — the chart simply plots whatever is in `skew_history` (up
to 30 days at 5-minute resolution, ~8,640 points/coin at full retention). If that proves too dense
to read or too slow to render, downsampling can be added later; out of scope for this pass.

## Testing

- `position_skew.py`: `SkewSnapshot` is a plain dataclass, no new logic to test beyond
  construction; existing `compute_skew`/`next_zone`/`SkewTracker` tests are unaffected.
- `WhaleStorage` (`tests/ingestion/test_storage.py`): `insert_skew_snapshots`
  dedups on `(coin, timestamp)`, prunes rows older than 30 days relative to the batch's own
  latest timestamp while keeping newer ones, and `recent_skew_history` returns only the
  requested coin's rows in ascending timestamp order.
- `HyperdashAdapter` (`test_hyperdash.py`): a `fetch()` call produces a `SkewSnapshot` for every
  watched coin (including zero-position coins) on the first poll; a second `fetch()` within 5
  minutes produces no new snapshots; a third `fetch()` after the throttle window produces new
  ones with updated totals. Existing alert/position tests unaffected since `_update_skew`'s
  alert-producing logic is unchanged, only extended.
- `scheduler.py` (`test_scheduler.py`): `poll_once` calls `storage.insert_skew_snapshots` with
  whatever `adapter.consume_skew_snapshots()` returns, using a fake adapter/storage.
- `DashboardService` (`tests/dashboard/test_service.py`): `_load_coin_positions` populates
  `CoinPositionTable.skew_history` from `WhaleStorage.recent_skew_history` for each watched coin.
- `web.py` / template tests (`test_web.py`): a coin panel's response includes a `canvas` with
  `class="skew-chart"` and a `data-skew` attribute containing the expected JSON-encoded history.
