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
- `adapters/*.py` — one file per data source. Only `hyperliquid.py` exists so far.
- `registry.py` — builds the list of adapters whose `is_configured()` is true.
- `storage.py` — SQLite (`data/whale.db`, gitignored) with dedup on `(source, dedup_key)`.
- `scheduler.py` — runs every configured adapter concurrently, each on its own
  `poll_interval_seconds`.
- `config.py` — `pydantic-settings` reading `.env` (see `.env.example`); every adapter's
  credentials are optional, so the service runs with whatever subset is configured.

`src/hello_coin/cli.py` is the entry point: `hello-coin ingest run` starts the service,
`hello-coin ingest test <source>` fetches once from one adapter and prints the result.

No decision engine, technical indicators, or trade execution code exists yet — those are
separate, not-yet-planned pieces of the product intent below.

## Product intent

This is a crypto trading system. Per the project owner:

- Continuously track whale (large holder) activity — on-chain movements, exchange order flow, accumulation/
  distribution.
- Combine whale signals with technical indicators (trend, momentum, volatility, volume).
- Use AI to decide trade entries and exits from the combined signal.
- Decision weighting: whale activity ≈ 70%, technical indicators ≈ 30%. Any scoring/decision logic should
  preserve this weighting rather than treating the two signal sources as equal inputs.

## Tooling already available in this Claude Code environment

This session has MCP servers and skills connected that map directly onto the product intent above — prefer
wiring the eventual implementation to reuse these rather than re-implementing equivalent data fetching from
scratch:

- `market-intel` skill / `mcp__market-data__*` tools — whale activity, exchange flows, token unlocks, ETF
  flows, DeFi TVL, on-chain cycle indicators. This is the primary source for the 70%-weighted whale signal.
- `technical-analysis` skill — trend/momentum/volatility/volume indicators (MACD, RSI, BOLL, EMA, ATR, etc.)
  for the 30%-weighted technical signal.
- `sentiment-analyst` skill — funding rates, long/short ratio, open interest, fear & greed — a possible
  secondary input if the design later separates sentiment from pure whale/TA signals.
- `macro-analyst` skill — broader macro/cross-asset context (rates, DXY, risk-on/off).
- `bitget-skill` — order placement/cancellation, positions, leverage, balances on Bitget; the likely execution
  layer once a decision engine exists.

When implementation starts, confirm with the user which exchange(s) and data sources are actually in scope
before assuming Bitget/`market-data` are the final choices.
