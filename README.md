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
2. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
3. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.

## Test

```
uv run pytest
```

## Lint

```
uv run ruff check .
```
