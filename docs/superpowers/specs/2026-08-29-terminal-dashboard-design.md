# Terminal Dashboard Design

## Goal

Add a read-only terminal dashboard that continuously shows whale activity, technical
indicators, and a deterministic market-bias signal for the configured market symbols.
Users start the entire MVP with `uv run hello-coin dashboard`.

## Scope

The dashboard is a local Textual application. It starts whale ingestion and technical
collection in the background, refreshes its displayed snapshot every 60 seconds, and
never sends an order. It does not invoke Anthropic, start the decision engine, or start
the optional Coinglass liquidation service.

Existing `ingest`, `technical`, `liquidation`, and `decision` CLI commands remain
unchanged.

## Command and Lifecycle

`hello-coin dashboard` will:

1. Load the existing `Settings` from `.env`.
2. Start the configured ingestion adapters as an asynchronous Textual worker.
3. Start technical snapshot collection as an asynchronous Textual worker with a 60-second
   polling interval.
4. Open the Textual dashboard and render its first snapshot immediately.
5. Re-read the SQLite-backed data at a 60-second interval.
6. Cancel both background workers and close every SQLite connection on quit or Ctrl+C.

Adapter-specific polling intervals remain authoritative. For example, a 300-second paid
source is displayed as stale between its successful polls rather than being polled more
often by the dashboard.

## Data Flow

```text
configured ingestion adapters ─┐
                               ├─> data/whale.db ─┐
technical snapshot collector ──┘                  │
                                                   ├─> dashboard service ─> Textual widgets
technical snapshot collector ───> data/technical.db┘
```

The dashboard service only reads persisted data. It does not make HTTP requests. This
keeps UI rendering independent of network latency and lets a failing external adapter
leave all remaining sources and panels usable.

The service will obtain the latest technical snapshot, recent whale events and metrics,
and each source's latest observed timestamp. Storage gains focused read methods where
the existing API cannot return this data. Reads return `None` or an empty collection when
no persisted data exists; the dashboard must never fabricate a neutral value.

## Market Bias

The MVP deliberately has no LLM decision. For the selected symbol it reuses the existing
pure score functions:

- `compute_whale_score` for the base asset's whale events and relevant metrics.
- `compute_technical_score` for the latest configured timeframe snapshot.

When both scores are available, the dashboard computes:

```text
market_bias_score = whale_score * 0.70 + technical_score * 0.30
```

The displayed label is:

- `BULLISH BIAS` when the score is at least `0.25`.
- `BEARISH BIAS` when the score is at most `-0.25`.
- `WAIT` otherwise.
- `INSUFFICIENT DATA` when either component is unavailable.

The panel explicitly labels this as a rule-based, informational market bias rather than
investment advice or an automated entry/exit order.

## Terminal Experience

The initial screen uses the approved one-screen layout:

- Header with live status and countdown to the next 60-second render refresh.
- Market overview for the selected symbol: current close, timeframe, and trend context.
- Technical panel: RSI, MACD state, EMA context, Bollinger levels when available.
- Market-bias panel: label, numeric score, and its available whale/technical components.
- Whale-activity table: the most recent persisted relevant events.
- System-status panel: ingestion, technical, optional data, stale, and unavailable states.
- Footer that states the product is informational and shows key bindings.

The active symbol defaults to the first `EXCHANGE_WATCH_SYMBOLS` value. `1` through `9`
select the corresponding configured symbol. `r` refreshes the display immediately, and
`q` quits. If there are more than nine configured symbols, the first nine are selectable
in this MVP and the limitation is shown in the footer.

## Error and Staleness Behavior

The dashboard stays open when an adapter, SQLite read, or background worker fails. A
failed refresh preserves the last successful snapshot for that panel and presents an
error or stale label with the last update timestamp. The next scheduled refresh retries
the read. Missing optional configuration is shown as `NOT CONFIGURED`, never as a failure.

## Implementation Shape

Create `src/hello_coin/dashboard/` with these focused responsibilities:

- `models.py`: immutable view data used by the UI and tests.
- `service.py`: storage-to-view-model reads, freshness evaluation, and market-bias mapping.
- `app.py`: Textual layout, refresh timer, key bindings, and lifecycle of the two background
  workers.

`src/hello_coin/cli.py` adds only the `dashboard` subcommand and a runner that constructs
the app. `pyproject.toml` gains the `textual` dependency. Storage modules add the smallest
read APIs required by `dashboard.service`.

## Testing and Validation

Tests mirror the new package under `tests/dashboard/` and are written before production
code. They cover:

- market-bias weights, thresholds, and incomplete input;
- latest/recent storage reads and empty-data behavior;
- source freshness and error presentation;
- symbol selection and immediate refresh bindings with Textual's headless `run_test()`;
- no Anthropic client creation and no exchange-order code path from the dashboard command;
- graceful cancellation and resource closure of dashboard background tasks.

Normal validation is `uv run pytest` and `uv run ruff check .`, followed by a manual
terminal smoke test of `uv run hello-coin dashboard` using the configured local data
sources. Network tests remain opt-in and are not required for the offline suite.

## Out of Scope

- Browser UI, HTTP API, authentication, or multi-user hosting.
- Placing, cancelling, or managing exchange orders.
- Anthropic-backed decisions and Coinglass liquidation collection.
- Historical charting, alerts, backtesting, or portfolio tracking.
