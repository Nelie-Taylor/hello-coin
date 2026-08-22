# Technical Indicators — Design

Date: 2026-08-22
Status: Approved by user, pending implementation plan

## Purpose

hello-coin is an AI-driven crypto trading system where whale activity drives ~70% of
entry/exit decisions and technical indicators drive ~30%. The whale-data ingestion layer
(`src/hello_coin/ingestion/`) is complete. This design covers the second signal source: a
continuously running service that fetches OHLCV candle data and computes standard technical
indicators (trend/momentum/volatility), storing normalized snapshots for the (not-yet-built)
decision engine to consume alongside whale data.

**Critical platform note, carried over from the ingestion design:** the `technical-analysis`
skill available inside this interactive Claude Code session is **not reachable from a
standalone Python process**. This module therefore fetches raw price data itself and computes
every indicator locally — it does not call the skill.

## Scope

- Fetch OHLCV (open/high/low/close/volume) candles from Binance Futures' public klines
  endpoint (`GET https://fapi.binance.com/fapi/v1/klines`) — no API key needed, confirmed live
  during design (`curl` returned real candle arrays for `BTCUSDT`/`1h`).
- Compute five standard indicators from that candle history, purely in Python (no pandas/numpy
  — matches this repo's existing lightweight dependency footprint):
  - **RSI** (Relative Strength Index, momentum) — Wilder's smoothing, 14-period default.
  - **MACD** (Moving Average Convergence Divergence, trend) — 12/26/9 EMA-based, standard.
  - **Bollinger Bands** (volatility) — 20-period SMA ± 2 standard deviations, standard.
  - **EMA** (Exponential Moving Average, trend) — standard smoothing formula.
  - **ATR** (Average True Range, volatility) — Wilder's smoothing, 14-period default.
- Watch the same symbol list as whale ingestion (`exchange_watch_symbols`, default
  `["BTCUSDT"]`) — one shared config surface instead of a second, redundant symbol list.
- Store one `IndicatorSnapshot` per symbol per poll in SQLite, so the decision engine can read
  indicator history, not just the latest value.

Explicitly out of scope: the decision engine (70/30 scoring), trade execution, and any
indicator beyond the five listed above (more can be added later following the same pattern).

## Architecture

A new top-level package, `src/hello_coin/technical/`, sibling to `ingestion/` — not nested
inside it, since it's a conceptually separate signal source that a future decision engine reads
from independently:

```
src/hello_coin/
  technical/
    models.py       # Candle, IndicatorSnapshot
    klines.py        # fetch_klines(symbol, interval, limit) -> list[Candle]
    indicators.py     # pure functions: rsi(), macd(), bollinger_bands(), ema(), atr()
    service.py         # combines klines + indicators -> IndicatorSnapshot for one symbol
    storage.py          # SQLite schema + insert/query, mirrors ingestion/storage.py's shape
    scheduler.py          # polls every watched symbol on an interval
  ingestion/           # existing whale-data layer, unchanged
  cli.py                # gains `technical run` / `technical test <symbol>` subcommands
```

`indicators.py` functions take plain `list[float]` (or parallel high/low/close lists for ATR)
and return plain floats/tuples — no dependency on `Candle` or any HTTP code, so they're testable
against known reference values with zero mocking. `klines.py` is the only network-facing module;
`service.py` is the only place that wires fetching + computing together. This mirrors the
ingestion layer's separation (adapter fetches → separate storage/scheduler layers), scaled down
because there's only one data source here instead of thirteen.

No `Adapter`-style registry is needed — there's one data source (Binance klines), not many, so
`scheduler.py` iterates directly over `exchange_watch_symbols` rather than a list of pluggable
adapters.

## Data model

```python
@dataclass
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class IndicatorSnapshot:
    symbol: str
    timeframe: str            # e.g. "1h"
    timestamp: datetime       # candle open_time this snapshot was computed from
    close_price: float
    rsi: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    ema: float | None
    atr: float | None
    raw: dict                 # the candle list used, for debugging/reprocessing
```

Every indicator field is `float | None` because each needs a minimum number of candles to
produce a value (e.g. RSI-14 needs 15 candles); with too little history a field is `None`
rather than a fabricated number. `service.py` fetches enough candles up front (see Scheduling)
that in normal operation every field is populated after the first poll.

## Storage

SQLite file at `data/technical.db` (gitignored, alongside `data/whale.db`). One table:

```sql
CREATE TABLE technical_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    close_price REAL NOT NULL,
    rsi REAL,
    macd_line REAL,
    macd_signal REAL,
    macd_histogram REAL,
    bb_upper REAL,
    bb_middle REAL,
    bb_lower REAL,
    ema REAL,
    atr REAL,
    raw TEXT NOT NULL,
    UNIQUE(symbol, timeframe, timestamp)
)
```

`UNIQUE(symbol, timeframe, timestamp)` dedupes exactly like the ingestion tables' `UNIQUE(source,
dedup_key)` — re-polling the same closed candle is a no-op insert.

## Config

Reuses `exchange_watch_symbols` from the existing `Settings` (no new symbol list). Adds one new
field:

```python
technical_timeframe: str = "1h"
```

No API key needed — Binance's public klines endpoint requires none.

## Scheduling

`scheduler.py` polls every symbol in `exchange_watch_symbols` every **15 minutes** (a 1h-candle
series doesn't need finer-grained polling than that; 15 minutes catches the candle close
promptly without hammering the endpoint). Each poll fetches enough recent candles to seed every
indicator (RSI/ATR need 14+1, MACD needs 26+9, Bollinger needs 20 — fetching **100** candles per
poll comfortably covers all of them with margin), computes one `IndicatorSnapshot` from the
latest closed candle, and stores it.

## Error handling

Same posture as the ingestion layer: transient errors (timeout, 5xx, 429) are logged and retried
on the next scheduled tick; no in-tick retry storm. Klines fetch failures don't crash the
service — `service.py` propagates the exception, the scheduler logs it and continues to the next
symbol/tick (mirroring `Adapter.safe_fetch`'s failure-counting, reimplemented here at the
scheduler level since there's no `Adapter` base class in this module).

## Testing

- Every indicator function in `indicators.py` is tested against **known reference values** —
  worked examples with a hand-computable or well-established expected result (e.g. a short
  price series with a manually verified RSI/EMA), not live API data. These are pure functions,
  so no mocking is needed.
- `klines.py` is tested against a mocked HTTP response (`respx`), asserting the parsed `Candle`
  list matches Binance's documented array-of-arrays shape (already confirmed live and reused
  from the existing Binance derivatives adapter's `_TRANSFERS`-equivalent verification).
- One real-network smoke test (`@pytest.mark.network`) against the live, no-auth Binance klines
  endpoint, confirming the full fetch → compute → snapshot pipeline runs end to end against real
  data — same pattern as the Hyperliquid/exchange-derivatives smoke tests.

## Open items for the implementation plan

- Exact task breakdown and ordering (models → indicators → klines → service → storage →
  scheduler → CLI wiring) — a planning decision, not a design decision.
