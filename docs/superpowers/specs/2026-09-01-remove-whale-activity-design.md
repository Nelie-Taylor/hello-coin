# Remove Whale Activity (keep hyperdash position-skew) — Design

Date: 2026-09-01
Status: approved by owner ("ổn, làm đi")

## Goal

Remove the whale-activity feature entirely — whale event/metric adapters, whale scoring, and
the whale weighting in the decision engine — while keeping the hyperdash position-skew
tracking that the dashboard's skew charts, coin-position tables, coin price overlay, and
Telegram LONG/SHORT alerts are built on.

## What is removed

### Adapters (`src/hello_coin/ingestion/adapters/`)

Deleted, plus their tests:

- `binance.py`, `okx.py`, `bybit.py`, `bitget.py` (exchange whale metrics)
- `etherscan.py` (all three chain registrations)
- `cryptoquant.py`, `debank.py`, `nansen.py`, `whale_alert.py`, `bitquery.py`
- `hyperliquid.py` (whale fills; the coin-price fetch via allMids lives in `hyperdash.py`,
  not here, so this is safe to delete)

Kept: `base.py` (Adapter ABC + safe_fetch), `hyperdash.py`.

`registry.py` registers only `HyperdashAdapter`.

### Models and storage (`src/hello_coin/ingestion/`)

- `WhaleMetric` deleted from `models.py`; `WhaleEvent` stays (hyperdash persists positions as
  `position` events).
- `WhaleStorage`: metric methods and the metrics table usage are removed; events + skew
  snapshot tables are unchanged. `data/whale.db` is NOT deleted — it holds the 30-day skew
  history. Existing tables that become unused are left in place (no destructive migration).
- `config.py` and `.env.example`: credentials/settings for the deleted adapters are removed
  (etherscan, cryptoquant, debank, nansen, whale_alert, bitquery keys and related knobs).
  Settings used by hyperdash, telegram, dashboard, technical, liquidation, decision stay.

### Decision engine (`src/hello_coin/decision/`)

- `whale_score.py` deleted. (`base_asset()` was planned to move to a shared module, but after
  the rework nothing used it anymore — dashboard and decision both stopped reading whale
  events by symbol — so it was deleted outright.)
- New weighting: **technical 60% / liquidation 40%** when both are available; when the
  liquidation signal is missing (Coinglass not configured), technical carries 100%. No
  interpolation between the splits.
- `SYSTEM_PROMPT` in `service.py` rewritten for the two-signal scheme.
- `Decision` model drops `whale_score`. The existing `whale_score` column in
  `data/decisions.db` stays in the schema as nullable (insert NULL / omit); no migration.

### Dashboard (`src/hello_coin/dashboard/`)

- Whale events feed/table removed from templates and `DashboardSnapshot`.
- Market bias no longer takes a whale component — bias derives from the technical score only.
- Source-status list shrinks naturally to hyperdash (registry change).
- Kept as-is: coin position tables, skew charts with price overlay and tooltips, hyperdash
  status, technical panel.

### Docs

- `CLAUDE.md`: product intent (weighting becomes technical 60 / liquidation 40, fallback
  technical 100) and architecture sections rewritten; whale ingestion description reduced to
  the hyperdash/skew pipeline.
- Old spec/plan docs under `docs/superpowers/` are historical records and stay untouched.

## What is explicitly kept

- `hyperdash.py` adapter: position fetch, skew computation, coin price via Hyperliquid
  allMids, skew snapshots, Telegram `SkewAlert` notifications.
- `position_skew.py`, `notifications.py` (TelegramNotifier).
- Skew history in `data/whale.db`.
- The `ingest run` / `ingest test <source>` CLI commands (now hyperdash-only) and the
  in-process ingestion worker started by the dashboard.

## Verification

- `uv run pytest` green (tests for deleted code removed; dashboard/decision tests updated).
- `uv run ruff check .` green.
- Docker image rebuilt and restarted so the owner can review the running dashboard.

## Out of scope

- GitHub Actions Docker build workflow (separate, previously discussed plan — to be done
  after this removal).
- Renaming the `ingestion` package or `whale.db` (cosmetic; deferred to avoid breaking the
  stored skew history and running setup).
