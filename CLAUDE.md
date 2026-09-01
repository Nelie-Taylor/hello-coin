# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack and commands

Python project managed with `uv` (src layout, package `hello_coin` under `src/hello_coin/`).

- Install/sync dependencies: `uv sync`
- Run the app: `uv run hello-coin` (entry point: `hello_coin:main`)
- Run tests: `uv run pytest` — single test: `uv run pytest tests/ingestion/test_models.py::test_whale_event_holds_fields`
  (network-marked tests are excluded by default; run them with `uv run pytest -m network`)
- Lint: `uv run ruff check .`
- Add a dependency: `uv add <package>` (dev-only: `uv add --dev <package>`)

## Architecture

`src/hello_coin/ingestion/` is the position-skew ingestion layer (historically the whale-data
layer — the whale-activity feature was removed on 2026-09-01, see
`docs/superpowers/specs/2026-09-01-remove-whale-activity-design.md`; the package and
`data/whale.db` keep their names so stored skew history survives):

- `models.py` — `WhaleEvent`: hyperdash persists whale positions as `position` events.
- `adapters/base.py` — `Adapter` abstract base: subclasses implement only `fetch()`;
  `safe_fetch()` handles logging and disabling a source after repeated failures.
- `adapters/hyperdash.py` — the only adapter: fetches whale positions per watched coin from
  Hyperdash, computes LONG/SHORT skew, samples skew snapshots (with the coin price from
  Hyperliquid's public `allMids` endpoint), and emits `SkewAlert`s on dominance transitions.
- `position_skew.py` — skew computation, `SkewSnapshot`, `SkewAlert`.
- `notifications.py` — `TelegramNotifier` delivering LONG/SHORT dominance alerts.
- `registry.py` — builds the adapter list (just hyperdash) when `is_configured()` is true.
- `storage.py` — SQLite (`data/whale.db`, gitignored): position events deduped on
  `(source, dedup_key)` plus 30-day skew snapshot history.
- `scheduler.py` — polls each configured adapter on its own `poll_interval_seconds`.
- `config.py` — `pydantic-settings` reading `.env` (see `.env.example`); all credentials are
  optional, so the service runs with whatever subset is configured.

`src/hello_coin/technical/` is the technical-indicators layer (the 60%-weighted signal; 100%
when the liquidation signal is unavailable), see
`docs/superpowers/specs/2026-08-22-technical-indicators-design.md`:

- `models.py` — `Candle` and `IndicatorSnapshot` (all indicator fields `float | None`; `None`
  means not enough history yet, never a fabricated number).
- `indicators.py` — pure functions: `rsi()`, `macd()`, `bollinger_bands()`, `ema()`, `atr()`.
  No HTTP, no models — testable against hand-verified reference values with zero mocking.
- `klines.py` — fetches OHLCV candles from Binance's public futures klines endpoint (no key).
- `service.py` — combines `klines.py` + `indicators.py` into one `IndicatorSnapshot`.
- `storage.py` — SQLite (`data/technical.db`, gitignored) with dedup on
  `(symbol, timeframe, timestamp)`.
- `scheduler.py` — polls every symbol in `exchange_watch_symbols` every 15 minutes. No
  `Adapter`-style registry — there's one data source here, not many.

`src/hello_coin/liquidation/` is the liquidation-heatmap layer (the 40%-weighted signal, folded
into the decision engine's weighted score alongside the technical signal), see
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

`src/hello_coin/decision/` is the AI decision engine (combines the signals above), see
`docs/superpowers/specs/2026-08-22-decision-engine-design.md`:

- `models.py` — `Decision` (symbol, scores, action/confidence/reasoning, raw LLM response).
  The `decisions.db` schema keeps a legacy nullable `whale_score` column from the removed
  whale signal; new rows store NULL there.
- `technical_score.py` — aggregates the latest `data/technical.db` snapshot into `[-1, 1]` (or
  `None`) from RSI/MACD/Bollinger/EMA.
- `llm.py` — calls the Anthropic API via tool use for a structured `action`/`confidence`/
  `reasoning` decision. No real-network test — every call costs money.
- `service.py` — combines technical/liquidation scores (0.60/0.40 when both are available;
  technical carries 100% when the liquidation signal is missing — never silently re-weighted
  to anything in between) into the LLM prompt, along with the nearest liquidation cluster
  price levels for entry/exit context, and parses the result into a `Decision`.
- `storage.py` — SQLite (`data/decisions.db`, gitignored) with dedup on `(symbol, timestamp)`.
- `scheduler.py` — polls every symbol in `exchange_watch_symbols` every 1 hour.

`src/hello_coin/cli.py` is the entry point: `hello-coin ingest run` / `hello-coin technical run`
/ `hello-coin liquidation run` / `hello-coin decision run` start the four services; `hello-coin
ingest test <source>` / `hello-coin technical test <symbol>` / `hello-coin liquidation test
<symbol>` / `hello-coin decision test <symbol>` fetch, compute, or decide once and print the
result.

No trade execution code exists yet — placing real orders needs the target exchange(s) confirmed
with the user first (see the "Tooling" section below), which hasn't happened.

## Product intent

This is a crypto trading system. Per the project owner:

- The whale-activity feature (on-chain movements, exchange order flow, whale scoring) was
  **removed entirely on 2026-09-01** at the owner's request — do not re-add it. What remains
  from that era is the hyperdash position-skew tracking (dashboard skew charts, coin position
  tables, Telegram dominance alerts), which the owner explicitly kept.
- Combine technical indicators (trend, momentum, volatility, volume) with the liquidation
  heatmap and use AI to decide trade entries and exits from the combined signal.
- Decision weighting: technical indicators ≈ 60%, liquidation heatmap ≈ 40% when both signals
  are available. When the liquidation signal is unavailable (e.g. Coinglass not configured),
  the technical score carries 100%. Any scoring/decision logic should preserve these fixed
  splits rather than interpolating between them or treating all signal sources as equal inputs.

## Tooling already available in this Claude Code environment

This session has MCP servers and skills connected that map directly onto the product intent above — prefer
wiring the eventual implementation to reuse these rather than re-implementing equivalent data fetching from
scratch:

- `market-intel` skill / `mcp__market-data__*` tools — exchange flows, token unlocks, ETF flows, DeFi
  TVL, on-chain cycle indicators. (Formerly the primary source for the removed whale signal — do not
  wire it back in for that purpose without the owner asking.)
- `technical-analysis` skill — trend/momentum/volatility/volume indicators (MACD, RSI, BOLL, EMA, ATR, etc.)
  for the technical signal (≈60% weighted; 100% when the liquidation signal is unavailable).
- `sentiment-analyst` skill — funding rates, long/short ratio, open interest, fear & greed — a possible
  secondary input if the design later separates sentiment from the TA signal.
- `macro-analyst` skill — broader macro/cross-asset context (rates, DXY, risk-on/off).
- `bitget-skill` — order placement/cancellation, positions, leverage, balances on Bitget; the likely execution
  layer once a decision engine exists.

When implementation starts, confirm with the user which exchange(s) and data sources are actually in scope
before assuming Bitget/`market-data` are the final choices.
