# Whale Data Ingestion — Design

Date: 2026-08-22
Status: Approved by user, pending implementation plan

## Purpose

hello-coin is an AI-driven crypto trading system where whale (large-holder) activity drives
~70% of entry/exit decisions and technical indicators drive ~30%. This design covers the
**ingestion layer**: a continuously running service that pulls raw whale data from 13 external
sources, normalizes it, and stores it for later consumption by the (not-yet-built) decision
engine. Technical indicators are out of scope here — covered separately by the
`technical-analysis` skill already available in this environment.

## Scope

All 13 sources compiled during research are in scope from the start, split into two shapes of
data:

- **Discrete whale events** (a transfer, a fill, a position snapshot tied to one wallet):
  Hyperliquid, ClankApp, Etherscan-family (Etherscan/BscScan/Polygonscan/Solscan), DeBank,
  Whale Alert, Bitquery, Nansen, Arkham.
- **Aggregate whale metrics** (a ratio/index/reserve number over time, not tied to one wallet):
  CryptoQuant, Binance, OKX, Bybit, Bitget.

Several sources require a paid subscription the user has not necessarily set up yet (Whale
Alert, Bitquery, Nansen, Arkham, CryptoQuant). The design handles this by making every adapter
independently "configured or not" — the service must run correctly with only the free sources
active and pick up paid sources automatically once their API key is added to `.env`.

Explicitly out of scope for this design: the decision engine (70/30 scoring), trade execution,
technical indicators, and any UI/dashboard.

## Architecture

Adapter pattern + async poller, chosen over a single monolithic script (doesn't scale to 13
different rate limits/schedules — one slow source blocks all others) or a message-queue pipeline
(adds infra — Redis/RabbitMQ — not justified for a local, solo-run service at this stage).

```
src/hello_coin/
  ingestion/
    models.py        # WhaleEvent, WhaleMetric
    adapters/
      base.py         # abstract Adapter: name, poll_interval, is_configured(), fetch()
      hyperliquid.py
      etherscan.py     # Ethereum/BSC/Polygon via Etherscan's unified V2 API (chainid param);
                       # implemented, fully verified. Solscan is a separate, non-EVM API.
      solscan.py       # DEFERRED — paid-only ($49/mo min), response schema unverified
      clankapp.py      # DEFERRED — unverified as of 2026-08-22, clankapp.com blocks
                       # automated fetches and its api./docs. subdomains don't resolve
      debank.py        # DeBank Cloud (paid, unit-based AccessKey) — implemented, fully
                       # verified. Superseded the originally-planned free "Open API".
      whale_alert.py   # global feed, min_value filter — implemented, response schema
                       # secondhand-sourced (see 2026-08-22-freemium-paid-adapters.md)
      bitquery.py      # GraphQL, global feed — implemented, query shape not 100%
                       # verbatim-confirmed (see 2026-08-22-freemium-paid-adapters.md)
      nansen.py        # per-wallet labeled transactions — implemented, fully verified
      arkham.py        # DEFERRED — HMAC signing scheme undocumented, not implemented
      cryptoquant.py   # exchange whale ratio — implemented, fully verified
      binance.py
      okx.py
      bybit.py
      bitget.py
    registry.py       # builds the list of adapters whose is_configured() is true
    storage.py        # SQLite schema + insert/query, no business logic
    scheduler.py       # asyncio loop per adapter at its own poll_interval
    config.py          # pydantic-settings reading .env, one optional field per adapter's key(s)
  cli.py              # `hello-coin ingest run` (long-running service)
                       # `hello-coin ingest test <source>` (one-shot fetch, prints result)
```

Each adapter implements only `async fetch(self) -> list[WhaleEvent] | list[WhaleMetric]` plus
`is_configured(self) -> bool`. It knows nothing about scheduling or storage — this keeps each
adapter independently testable (mock the HTTP call, assert the parsed output) and means adding
or removing a source never touches the scheduler or storage code.

**Important platform note:** the `mcp__market-data` MCP tools and `bitget-skill` available
inside this interactive Claude Code session are NOT reachable from a standalone Python process.
The Binance/OKX/Bybit/Bitget adapters therefore call each exchange's public REST endpoints
directly — all of the specific endpoints used below require no API key.

## Data models

```python
@dataclass
class WhaleEvent:
    source: str
    timestamp: datetime
    chain_or_exchange: str
    symbol: str
    event_type: str          # "transfer" | "fill" | "position"
    side: str | None         # "buy" | "sell" | "long" | "short" | None for transfers
    amount: float
    amount_usd: float | None
    wallet_address: str | None
    raw: dict                # original payload, for debugging/reprocessing

@dataclass
class WhaleMetric:
    source: str
    timestamp: datetime
    symbol: str
    metric_name: str          # e.g. "top_trader_long_short_ratio", "exchange_whale_ratio"
    value: float
    raw: dict
```

## Storage

SQLite file at `data/whale.db` (gitignored). Two tables mirroring the models above:
`whale_events` and `whale_metrics`, each with a `UNIQUE(source, raw_id)`-style constraint (exact
dedup key chosen per adapter during implementation, e.g. Hyperliquid fill hash, Whale Alert
transaction hash) so repeated polls don't duplicate rows. `storage.py` exposes only
`insert_events()`, `insert_metrics()`, and basic read queries — it has no awareness of what
consumes the data later.

## Config & secrets

A `.env` file (gitignored) read via `pydantic-settings`. Each adapter declares its own optional
key field(s) (e.g. `ETHERSCAN_API_KEY`, `CLANKAPP_API_KEY`, `WHALE_ALERT_API_KEY`, `BITQUERY_API_KEY`,
`NANSEN_API_KEY`, `ARKHAM_API_KEY`, `CRYPTOQUANT_API_KEY`, `DEBANK_ACCESS_KEY`). Adapters with no
required key (Hyperliquid, Binance, OKX, Bybit, Bitget) are always configured. `registry.py`
calls `is_configured()` on every adapter at startup and skips + logs a warning for any that
aren't — the service runs with whatever subset is available.

## Scheduling

Each adapter declares `poll_interval_seconds`, defaulted per its real rate limit:

| Adapter | Auth | Poll interval (default) |
|---|---|---|
| Hyperliquid | none | 20s |
| Binance (futures long/short, OI) | none | 30s |
| OKX (long/short, taker volume, OI) | none | 30s |
| Bybit (long/short, OI) | none | 30s |
| Bitget (long/short, OI) | none | 30s |
| ClankApp | free key (email) | 30s |
| Etherscan-family | free key | 60s (5 req/s cap on free tier) |
| DeBank Open API | free key | 60s |
| Whale Alert | paid | 60s |
| Bitquery | paid | 60s |
| Nansen | paid | 5min |
| Arkham | paid/token-gated | 5min |
| CryptoQuant | paid (free tier = 3 indicators only) | 5min |

`scheduler.py` runs all configured adapters concurrently via `asyncio.gather`, each in its own
`while True: fetch → store → sleep(interval)` loop, so one slow or failing source never blocks
the others.

## Error handling

- Transient errors (timeout, 5xx, HTTP 429) → log and let the next scheduled tick retry; no
  in-tick retry storm.
- Auth errors (401/403) → after a small number of consecutive failures, mark the adapter
  disabled for the rest of the process lifetime and log why (distinct from "not configured").
- Parse/schema errors (source changed its response shape) → log with the raw payload attached
  for debugging; that adapter's tick is skipped, the loop continues.

## Testing

- Per-adapter unit tests mock the HTTP layer (`respx` for `httpx`) and assert `fetch()` returns
  correctly parsed `WhaleEvent`/`WhaleMetric` objects from a recorded sample response.
- `storage.py` tested against an in-memory SQLite database.
- A small number of real-network smoke tests against no-auth endpoints (Hyperliquid, Binance)
  marked separately so they don't run in every CI invocation.

## Open items for the implementation plan

- Exact dedup key per adapter (varies by source's own ID scheme) — decided per-adapter during
  implementation, not blocking this design.
- Build order across the 13 adapters (framework first is a given; which adapters follow in what
  order is a planning decision, not a design decision).
