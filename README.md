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

## Test

```
uv run pytest
```

## Lint

```
uv run ruff check .
```
