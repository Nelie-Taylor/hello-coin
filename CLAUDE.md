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

`src/hello_coin/ingestion/` is the whale-data ingestion layer (see
`docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md` for the full design):

- `models.py` — `WhaleEvent` (discrete per-wallet actions) and `WhaleMetric` (aggregate
  indicators), the two normalized shapes every adapter produces.
- `adapters/base.py` — `Adapter` abstract base: subclasses implement only `fetch()`;
  `safe_fetch()` handles logging and disabling a source after repeated failures.
- `adapters/*.py` — one file per data source:
  - No key needed: `hyperliquid.py`, `binance.py`, `okx.py`, `bybit.py`, `bitget.py`.
  - Free key: `etherscan.py` (Ethereum/BSC/Polygon via Etherscan's unified V2 API — one class,
    three registered instances, one per `chainid`).
  - Paid/freemium key: `cryptoquant.py`, `debank.py`, `nansen.py`, `whale_alert.py`,
    `bitquery.py`, and (in `liquidation/`) `coinglass.py`. None of these have been
    smoke-tested against a real key — see
    `docs/superpowers/plans/2026-08-22-freemium-paid-adapters.md` for per-adapter confidence
    notes (Whale Alert and Bitquery parse their responses defensively since their exact
    response shape wasn't first-party-confirmed).
  - Deferred (not implemented — insufficient verification): ClankApp, Solscan, Arkham. See the
    same plan doc for why.
- `registry.py` — builds the list of adapters whose `is_configured()` is true.
- `storage.py` — SQLite (`data/whale.db`, gitignored) with dedup on `(source, dedup_key)`.
- `scheduler.py` — runs every configured adapter concurrently, each on its own
  `poll_interval_seconds`.
- `config.py` — `pydantic-settings` reading `.env` (see `.env.example`); every adapter's
  credentials are optional, so the service runs with whatever subset is configured.

`src/hello_coin/technical/` is the technical-indicators layer (the 30%-weighted signal), see
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

`src/hello_coin/decision/` is the AI decision engine (combines the signals above), see
`docs/superpowers/specs/2026-08-22-decision-engine-design.md`:

- `models.py` — `Decision` (symbol, scores, action/confidence/reasoning, raw LLM response).
- `whale_score.py` — aggregates recent `data/whale.db` rows into `[-1, 1]` (or `None`);
  `base_asset()` handles the symbol-convention mismatch across whale sources (documented
  limitation — see the spec).
- `technical_score.py` — aggregates the latest `data/technical.db` snapshot into `[-1, 1]` (or
  `None`) from RSI/MACD/Bollinger/EMA.
- `llm.py` — calls the Anthropic API via tool use for a structured `action`/`confidence`/
  `reasoning` decision. No real-network test — every call costs money.
- `service.py` — combines whale/technical/liquidation scores (0.60/0.25/0.15 when all three are
  available; falls back to the original 0.7/0.3 whale/technical split when the liquidation
  signal is missing — never silently re-weighted to anything in between) into the LLM prompt,
  along with the nearest liquidation cluster price levels for entry/exit context, and parses the
  result into a `Decision`.
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

- Continuously track whale (large holder) activity — on-chain movements, exchange order flow, accumulation/
  distribution.
- Combine whale signals with technical indicators (trend, momentum, volatility, volume).
- Use AI to decide trade entries and exits from the combined signal.
- Decision weighting: whale activity ≈ 60%, technical indicators ≈ 25%, liquidation heatmap ≈ 15% when
  all three signals are available. When the liquidation signal is unavailable (e.g. Coinglass not
  configured), falls back to whale ≈ 70% / technical ≈ 30% exactly as before — this fallback split
  supersedes the original "always 70/30" wording. Any scoring/decision logic should preserve these
  fixed splits rather than interpolating between them or treating all signal sources as equal inputs.

## Tooling already available in this Claude Code environment

This session has MCP servers and skills connected that map directly onto the product intent above — prefer
wiring the eventual implementation to reuse these rather than re-implementing equivalent data fetching from
scratch:

- `market-intel` skill / `mcp__market-data__*` tools — whale activity, exchange flows, token unlocks, ETF
  flows, DeFi TVL, on-chain cycle indicators. This is the primary source for the whale signal (≈70% or
  ≈60% weighted, depending on whether the liquidation signal is available — see Architecture above).
- `technical-analysis` skill — trend/momentum/volatility/volume indicators (MACD, RSI, BOLL, EMA, ATR, etc.)
  for the technical signal (≈30% or ≈25% weighted, same caveat).
- `sentiment-analyst` skill — funding rates, long/short ratio, open interest, fear & greed — a possible
  secondary input if the design later separates sentiment from pure whale/TA signals.
- `macro-analyst` skill — broader macro/cross-asset context (rates, DXY, risk-on/off).
- `bitget-skill` — order placement/cancellation, positions, leverage, balances on Bitget; the likely execution
  layer once a decision engine exists.

When implementation starts, confirm with the user which exchange(s) and data sources are actually in scope
before assuming Bitget/`market-data` are the final choices.
