# Hyperdash Per-Coin Terminal Dashboard

## Goal

Extend the read-only terminal dashboard so it discovers whale wallets per coin
through Hyperdash, then displays each coin's current Hyperliquid positions in a
separate table. The dashboard remains informational: it never creates an AI
client, submits orders, or changes a trader's account.

## Scope

The default Hyperdash watchlist mirrors `global-trade`:

```text
LINK,SOL,SUI,NEAR,HYPE
```

All Hyperdash access is optional. `HYPERDASH_API_TOKEN` is read from `.env`; no
credential is hard-coded, committed, or copied from another repository. The
watchlist and thresholds are configurable so a user can change them without a
code change:

- `HYPERDASH_WATCH_COINS` — comma-separated coin names.
- `HYPERDASH_API_TOKEN` — Hyperdash bearer token.
- `HYPERDASH_DELTA_TIMEFRAME` — defaults to `FIFTEEN_MINUTES`.
- `HYPERDASH_MIN_DELTA_USD` — defaults to `50000`.
- `HYPERDASH_MIN_POSITION_USD` — defaults to `50000`.

## Data flow

Every 60-second dashboard collection cycle:

1. For each configured coin, call Hyperdash GraphQL `GetPerpDeltas` with the
   configured timeframe.
2. Keep addresses whose absolute `current` delta is at least the configured
   minimum.
3. Deduplicate addresses across coins, then call Hyperliquid
   `clearinghouseState` once per candidate wallet.
4. For each wallet response, keep only non-zero positions for the requested
   coin whose absolute position value meets the configured minimum.
5. Normalize each position with coin, wallet address, side from the sign of
   `szi`, size, position value, entry price, liquidation price, unrealized PnL,
   return on equity, leverage value, leverage type, and observation timestamp.

Hyperdash discovery and Hyperliquid position reads are implemented as an
optional ingestion adapter. A missing token, HTTP error, malformed response, or
empty result for one coin must not prevent other coin tables from rendering.
The source health panel reports the affected coin/source as unavailable or
stale.

## Storage and freshness

Position observations may reuse the existing normalized whale-event storage,
but the dashboard must distinguish current position observations from
historical fills/transfers. Position rows are displayed only while their
observation timestamp is within the source freshness window (at most twice the
adapter poll interval, with a five-minute ceiling). Older rows are hidden from
the current-position table and retained only as historical storage if needed.

Historical fills remain separate from current positions and must not inherit
the current leverage value. A fill can show its own source-provided leverage
only when that field exists; otherwise it remains `N/A`.

## Terminal UI

The dashboard renders one scrollable table per configured coin. Each table has
these columns:

```text
Wallet | Side | Size | Position USD | Leverage | Entry | Liquidation | uPnL | Age
```

Side is `LONG` for positive `szi` and `SHORT` for negative `szi`. Leverage is
formatted as `7x` (or `cross · 7x` when the type is useful); missing leverage is
`N/A`. Wallet addresses are truncated for readability but remain identifiable
by prefix and suffix. Empty, stale, or failed tables show an explanatory row
instead of silently displaying old positions.

The existing market/technical/bias sections remain available. Numeric keys
continue to select configured symbols where applicable, `r` refreshes all
tables immediately, and `q` exits cleanly. Logging for the dashboard continues
to go to `data/dashboard.log`, never over the Textual screen.

## Error handling and safety

- Hyperdash is disabled and clearly labeled when its token is absent.
- Per-coin failures are isolated and rendered in that coin's table/status.
- No exception from an optional source closes the dashboard.
- The Hyperliquid client uses read-only `info` requests only.
- This feature does not invoke the decision or liquidation services and does
  not import or call any order-placement API.

## Testing and acceptance criteria

Tests must cover:

- settings parsing and safe defaults for the Hyperdash token, coins, timeframe,
  and thresholds;
- GraphQL request variables and per-coin delta filtering;
- deduplication of wallets before Hyperliquid state requests;
- position filtering, side derivation, leverage normalization, and malformed
  or missing fields;
- isolation when one coin's Hyperdash or Hyperliquid request fails;
- freshness filtering so stale positions are not presented as current;
- rendering of all five tables, empty/error states, and a real current-position
  row with leverage;
- existing dashboard controls and the no-AI/no-orders contract.

The normal offline suite must remain green. Network tests, if added, are
explicitly marked and never run by default.
