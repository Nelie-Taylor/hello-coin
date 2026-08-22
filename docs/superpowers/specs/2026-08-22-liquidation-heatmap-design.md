# Liquidation Heatmap Integration — Design

Date: 2026-08-22

## Summary

Add a third signal to the decision engine: a liquidation heatmap (predicted price levels
where large clusters of leveraged positions would be forced-closed), sourced from the
Coinglass API. This signal is used both as a scored input to the weighted decision formula
and as explicit price-level context in the LLM prompt, so the engine has a concrete basis for
choosing entry/exit prices and stop-loss/take-profit levels — not just a buy/sell/hold
direction.

This is a data-only integration. No chart rendering, dashboard, or visual UI is in scope —
the existing project is entirely backend/CLI services, and this follows that pattern.

## Why a new top-level module, not `ingestion/adapters/`

`ingestion/adapters/` is built around the `Adapter` base class for many sources producing
per-wallet `WhaleEvent`/aggregate `WhaleMetric` rows. A liquidation heatmap is a single-source,
single-snapshot-per-poll shape (price-level buckets at one point in time for one symbol) —
structurally identical to how `technical/` works (one source, one snapshot per poll), not to
the multi-adapter whale registry. `src/hello_coin/liquidation/` mirrors `technical/`'s module
layout instead of extending the `Adapter` base.

## Module layout

```
src/hello_coin/liquidation/
├── models.py      # LiquidationBucket, LiquidationSnapshot
├── coinglass.py   # HTTP fetch from Coinglass, is_configured()
├── score.py       # pure functions: heatmap -> liquidation_score [-1, 1], nearest_clusters()
├── service.py     # coinglass.py + score.py -> one LiquidationSnapshot
├── storage.py     # SQLite data/liquidation.db, dedup on (symbol, timestamp)
└── scheduler.py   # poll loop, mirrors technical/scheduler.py
```

## Data models (`liquidation/models.py`)

```python
@dataclass(frozen=True)
class LiquidationBucket:
    price: float
    notional_usd: float  # estimated leveraged value that liquidates at this price

@dataclass(frozen=True)
class LiquidationSnapshot:
    symbol: str
    timestamp: datetime
    current_price: float
    buckets: list[LiquidationBucket]
```

Buckets do not store a `side` field. Side is derived at scoring time from each bucket's price
relative to `current_price`: a bucket below current price is a long-liquidation cluster
(longs get force-sold as price falls); a bucket above is a short-liquidation cluster (shorts
get force-bought as price rises). This is the standard heatmap convention and avoids storing
a redundant field.

`decision/models.py`'s `Decision` gains one field: `liquidation_score: float | None`.

### Coinglass response shape is unconfirmed

As with `whale_alert.py` and `bitquery.py` (see
`docs/superpowers/plans/2026-08-22-freemium-paid-adapters.md`), the exact Coinglass heatmap
response shape has not been first-party-confirmed against a real key. `coinglass.py`/
`service.py` parse defensively — missing or malformed fields are skipped, never fabricated,
and a fully unparseable response yields `None` rather than raising.

## Scoring (`liquidation/score.py`)

Pure functions, no HTTP, no models beyond `LiquidationSnapshot` — testable with hand-built
buckets and zero mocking, matching the style of `whale_score.py` and `technical/indicators.py`.

```python
def compute_liquidation_score(
    snapshot: LiquidationSnapshot, proximity_pct: float = 0.10
) -> float | None:
```

1. Filter buckets within `±proximity_pct` of `current_price` (default ±10%) — distant clusters
   don't inform near-term entry/exit decisions.
2. Split into `long_clusters` (price < current_price) and `short_clusters` (price >
   current_price).
3. Weight each cluster by inverse distance, where
   `distance_pct = abs(bucket.price - current_price) / current_price` and
   `weight = 1 / distance_pct`. Closer clusters are more likely to be reached (and to cascade)
   sooner.
4. `score = (weighted_short_notional - weighted_long_notional) / (weighted_short_notional + weighted_long_notional)`.
   A large short-liquidation cluster above price biases bullish (price tends to get pulled up
   to sweep it); a large long-liquidation cluster below biases bearish. Range: `[-1, 1]`.
5. No buckets within the proximity window → returns `None` (never a fabricated neutral 0).

```python
def nearest_clusters(snapshot: LiquidationSnapshot, n: int = 2) -> dict:
    # {"long_below": [(price, notional_usd), ...], "short_above": [(price, notional_usd), ...]}
```

Returns the top-N largest clusters per side (by `notional_usd`) for use as LLM prompt context
— concrete price levels, not a score.

## Fetch, storage, scheduler (`liquidation/`)

- **`coinglass.py`**: `is_configured(settings)`, `async fetch_heatmap(symbol, api_key) -> dict`
  (raw JSON; parsing happens in `service.py`). 10s timeout, `raise_for_status()`, matching
  `technical/klines.py`.
- **`service.py`**: `async compute_snapshot(symbol, api_key) -> LiquidationSnapshot | None`.
  Calls `fetch_heatmap`, parses defensively, returns `None` on an empty/unusable response.
- **`storage.py`**: SQLite `data/liquidation.db` (gitignored, like the other stores). One row
  per snapshot with JSON-encoded buckets, dedup on `(symbol, timestamp)`. Exposes
  `latest_snapshot(symbol)` for `decision/service.py`.
- **`scheduler.py`**: mirrors `technical/scheduler.py` — one poll loop per symbol in
  `exchange_watch_symbols`, default interval 900s (15 min; heatmaps don't change fast and
  Coinglass is a paid API, so no need to poll tightly). If `is_configured()` is false, the loop
  does not run — no wasted calls, no error noise.

## Config (`ingestion/config.py`)

```python
coinglass_api_key: str | None = None
liquidation_proximity_pct: float = 0.10
liquidation_poll_interval_seconds: int = 900
```

All optional, following the existing pattern where every credential is optional and a missing
key just means that source is skipped. Documented in `.env.example` with a note that this
requires a paid Coinglass key.

## CLI (`cli.py`)

New subcommands mirroring `technical`:

```
hello-coin liquidation run
hello-coin liquidation test <symbol>
```

`decision run` / `decision test` open a `LiquidationStorage` alongside the existing whale/
technical storages and pass it into `compute_decision`.

## Decision engine integration (`decision/service.py`)

```python
async def compute_decision(
    symbol, timeframe,
    whale_storage, technical_storage, liquidation_storage,
    anthropic_client, model, whale_lookback_hours,
) -> Decision:
    ...
    liq_snapshot = liquidation_storage.latest_snapshot(symbol)
    liquidation_score = compute_liquidation_score(liq_snapshot) if liq_snapshot else None
    clusters = nearest_clusters(liq_snapshot) if liq_snapshot else None

    if whale_score is not None and technical_score is not None and liquidation_score is not None:
        weighted_score = 0.60 * whale_score + 0.25 * technical_score + 0.15 * liquidation_score
    elif whale_score is not None and technical_score is not None:
        weighted_score = 0.7 * whale_score + 0.3 * technical_score  # fallback: liquidation missing
    else:
        weighted_score = None
```

There is no interpolation between these two fixed weight sets — either all three signals are
present and the 60/25/15 split applies, or liquidation is missing and the original 70/30 split
applies exactly as before, or fewer than two signals are present and `weighted_score` is
`None`. This preserves the existing "never silently re-weight" principle while making
liquidation an optional third signal rather than a hard requirement — appropriate since
Coinglass is a paid source that may not always be configured.

`SYSTEM_PROMPT` is updated to describe both weighting formulas (and when each applies) and to
instruct the LLM to use the nearest liquidation cluster prices as a basis for concrete
entry/exit and stop-loss/take-profit levels, not just direction.

`_build_user_message` gains a `liquidation_score` line and the nearest long/short cluster
prices (from `nearest_clusters`) when available, or `"unavailable"` when not — same convention
as the existing whale/technical lines.

`decision/storage.py`'s SQLite schema gains a `liquidation_score` column. `data/decisions.db`
is gitignored, so no real migration path is needed — the schema-creation SQL is simply updated.

## Error handling

Follows the existing pattern throughout: `service.py`/`scheduler.py` catch exceptions, log,
and return `None`/0 rows rather than raising — one symbol's failure never blocks others
(`asyncio.gather` per symbol, as in `technical/scheduler.py`).

## Testing

- `score.py`: unit tests with hand-built `LiquidationSnapshot`/`LiquidationBucket` values
  (no mocking) — verify the distance-weighting formula, the long/short split, and the `None`
  case when no buckets fall inside the proximity window.
- `coinglass.py` / `service.py`: tests against sample JSON response fixtures (mocked HTTP);
  cover defensive parsing of missing/malformed fields. No real-network test, consistent with
  other paid-key sources.
- `decision/service.py`: tests for both weighting branches (all three signals present vs.
  liquidation missing, falling back to 70/30) using a stub storage whose `latest_snapshot`
  returns `None` or a snapshot as needed.

## Documentation follow-up

After implementation, update `CLAUDE.md`:

- Add `src/hello_coin/liquidation/` to the Architecture section (as described above).
- Update the `decision/service.py` bullet to describe the 60/25/15 formula with the 70/30
  fallback.
- Update **Product intent**'s weighting line: whale ≈ 60%, technical ≈ 25%, liquidation ≈ 15%
  when all three are available; falls back to whale 70%/technical 30% when liquidation is
  unavailable. This supersedes the original "70/30, never silently re-weighted" wording — note
  that explicitly so future sessions don't treat 70/30 as the only valid split.
- Add Coinglass to the "Paid/freemium key" adapters list, with the same "not yet smoke-tested
  against a real key" caveat as Whale Alert/Bitquery/etc.

## Out of scope

- Any chart rendering, image export, or dashboard/UI. This is a data pipeline + decision-engine
  input only.
- Real-time liquidation event streaming (individual force-close events) — this design covers
  only the aggregated heatmap.
- Trade execution using liquidation-derived entry/exit levels — no execution layer exists yet
  in this project (see CLAUDE.md's "Tooling" section).
