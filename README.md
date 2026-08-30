# hello-coin

Crypto trading system: continuously tracks whale (large holder) activity and combines it with technical
indicators to drive AI-based entry/exit decisions. Whale signal ≈ 70% of the decision weight, technical
indicators ≈ 30%.

## Setup

```
uv sync
```

## Run

```
uv run hello-coin
```

## Whale ingestion

1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
   `EXCHANGE_WATCH_SYMBOLS` defaults to `BTCUSDT` and needs no key — the Binance/OKX/Bybit/Bitget
   adapters work out of the box.
2. For the Etherscan-family adapters, register a free API key at
   [etherscan.io](https://etherscan.io/apis) and set `ETHERSCAN_API_KEY` plus
   `ETHERSCAN_WATCH_ADDRESSES` (comma-separated EVM wallet addresses) in `.env`. These adapters
   watch Ethereum, BSC, and Polygon with the same key/address list.
3. The paid/freemium adapters (CryptoQuant, DeBank, Nansen, Whale Alert, Bitquery) each need
   their own key in `.env` — see `.env.example` for the exact variable names. None of these
   have been verified against a real key in this environment; if a response shape turns out to
   differ from what's implemented, that adapter will show repeated failures in the logs and
   disable itself after a few consecutive misses (see `Adapter.safe_fetch` in
   `src/hello_coin/ingestion/adapters/base.py`) rather than crash the service.
4. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
   (or `binance`, `okx`, `bybit`, `bitget`, `etherscan_ethereum`, `etherscan_bsc`,
   `etherscan_polygon`, `cryptoquant`, `debank`, `nansen`, `whale_alert`, `bitquery`).
5. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.

## Technical indicators

1. No extra config needed — reuses `EXCHANGE_WATCH_SYMBOLS` from whale ingestion (default
   `BTCUSDT`) and defaults `TECHNICAL_TIMEFRAME` to `1h`.
2. Fetch once to sanity-check it: `uv run hello-coin technical test BTCUSDT`
3. Run the service continuously: `uv run hello-coin technical run` — writes to
   `data/technical.db`.

## Decision engine

1. Register an Anthropic API key at [console.anthropic.com](https://console.anthropic.com) and
   set `ANTHROPIC_API_KEY` in `.env`. Every call costs money — there's no free tier.
2. Compute one decision to sanity-check it: `uv run hello-coin decision test BTCUSDT`
   (needs `data/whale.db` and `data/technical.db` to already have some rows — run `ingest run`/
   `technical run` for a bit first, or the scores will both come back `None` and the LLM will
   see "unavailable" for everything).
3. Run the service continuously: `uv run hello-coin decision run` — writes to
   `data/decisions.db`. Polls once per hour per symbol.

## Web dashboard

Run `uv run hello-coin dashboard` to start local whale ingestion, technical collection, and a
web dashboard at `http://<DASHBOARD_HOST>:<DASHBOARD_PORT>/` (defaults to
`http://localhost:8080/`). The page refreshes every 60 seconds and shows a deterministic market
bias from whale (70%) and technical (30%) scores. It never sends orders and does not invoke the
Anthropic decision engine.

To enable Hyperdash per-coin whale discovery, set these optional values in `.env`:

```
HYPERDASH_API_TOKEN=your-token-here
HYPERDASH_WATCH_COINS=LINK,SOL,SUI,NEAR,HYPE
HYPERDASH_DELTA_TIMEFRAME=FIFTEEN_MINUTES
HYPERDASH_MIN_DELTA_USD=50000
HYPERDASH_MIN_POSITION_USD=50000
```

The dashboard shows one current-position table per configured coin, including LONG/SHORT,
position size, entry/liquidation, unrealized PnL, and leverage. Without a token, Hyperdash is
shown as `NOT CONFIGURED`; the rest of the dashboard continues to run.

To get whale position open/close alerts on Telegram instead of watching the dashboard, set
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (see `.env.example`). Without both set, no
alerts are sent — everything else keeps working.

## Run with Docker

```
docker compose up -d
```

Then open `http://localhost:8080/`. This runs the same thing as `uv run hello-coin dashboard`
(whale ingestion + technical indicators + web dashboard) inside a container; `./data` is mounted
into the container so `whale.db`/`technical.db`/`dashboard.log` persist across restarts. Copy
`.env.example` to `.env` and configure it exactly as described above first — `docker-compose.yml`
reads `.env` via `env_file`.

## Test

```
uv run pytest
```

## Lint

```
uv run ruff check .
```
