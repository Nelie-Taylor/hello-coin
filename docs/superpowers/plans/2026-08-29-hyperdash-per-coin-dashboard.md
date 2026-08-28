# Hyperdash Per-Coin Terminal Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover qualifying whale wallets per configured coin through Hyperdash and render their fresh Hyperliquid positions in separate terminal tables every 60 seconds.

**Architecture:** Add an optional `HyperdashAdapter` that performs one Hyperdash GraphQL delta query per coin, deduplicates qualifying wallets, and performs read-only Hyperliquid `clearinghouseState` calls. It emits normalized `WhaleEvent` rows with `event_type="position"`; the dashboard service groups only fresh Hyperdash positions by coin while retaining existing historical activity and technical panels. Textual renders a scrollable per-coin table and isolates unavailable/error states.

**Tech Stack:** Python 3.12, Pydantic Settings, httpx, SQLite `WhaleStorage`, Textual, pytest/respx.

**Spec:** `docs/superpowers/specs/2026-08-29-hyperdash-per-coin-dashboard-design.md`

## Global Constraints

- Default Hyperdash watchlist is `LINK,SOL,SUI,NEAR,HYPE`.
- `HYPERDASH_API_TOKEN` is loaded from `.env`; no credential is hard-coded or copied from `global-trade`.
- Defaults are `FIFTEEN_MINUTES`, `50000` USD delta threshold, and `50000` USD position threshold.
- Dashboard remains read-only, does not create an AI client, and never calls order-placement APIs.
- Per-coin/source failures must not stop other tables; missing token is clearly `NOT CONFIGURED`.
- Current positions are shown only within twice the adapter interval, capped at five minutes; historical fills do not inherit leverage.
- Normal offline `uv run pytest` and `uv run ruff check .` must remain green.

---

### Task 1: Add Hyperdash settings and normalized position helpers

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Create: `src/hello_coin/ingestion/adapters/hyperdash.py`
- Test: `tests/ingestion/test_config.py`
- Test: `tests/ingestion/test_hyperdash.py`

**Interfaces:**
- Produces `Settings.hyperdash_api_token: str | None`, `hyperdash_watch_coins: list[str]`, `hyperdash_delta_timeframe: str`, `hyperdash_min_delta_usd: int`, and `hyperdash_min_position_usd: int`.
- Produces `HyperdashAdapter(settings)`, `HyperdashAdapter.name == "hyperdash"`, `poll_interval_seconds == 60`, and `async fetch() -> list[WhaleEvent]`.
- Internal helpers parse Hyperdash deltas and Hyperliquid positions into `WhaleEvent(event_type="position")` with `raw` containing entry/liquidation/uPnL/ROE/leverage fields.

- [ ] **Step 1: Write failing settings tests** for empty-token defaults, `LINK,SOL` comma parsing, timeframe, and numeric thresholds from environment variables.
- [ ] **Step 2: Run `uv run pytest tests/ingestion/test_config.py -q`** and verify the new assertions fail because fields do not exist.
- [ ] **Step 3: Implement the five `Settings` fields and include `hyperdash_watch_coins` in the existing comma-splitting validator.** Keep list defaults isolated with `Field(default_factory=list)` or the project’s current compatible form, and preserve `_env_file=None` test behavior.
- [ ] **Step 4: Add failing pure tests for side (`szi > 0` LONG/buy, `< 0` SHORT/sell), absolute size/value, leverage normalization, and missing optional fields producing `None`/`N/A`-compatible raw values.**
- [ ] **Step 5: Run `uv run pytest tests/ingestion/test_hyperdash.py -q`** and verify the adapter module is not implemented yet.
- [ ] **Step 6: Add the adapter constants, GraphQL/Hyperliquid request helpers, strict numeric parsing, and a normalized position event helper.** Use `httpx.AsyncClient`, bearer auth only for Hyperdash, public Hyperliquid `info`, and no order endpoints.
- [ ] **Step 7: Run both focused test files and `uv run ruff check src/hello_coin/ingestion/config.py src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py`; expect PASS.**
- [ ] **Step 8: Commit with `git add ... && git commit -m "feat: add Hyperdash settings and position adapter"`.**

### Task 2: Implement per-coin discovery, wallet deduplication, and failure isolation

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/hyperdash.py`
- Modify: `src/hello_coin/ingestion/registry.py`
- Test: `tests/ingestion/test_hyperdash.py`
- Test: `tests/ingestion/test_registry.py`

**Interfaces:**
- `HyperdashAdapter.is_configured() -> bool` returns true only when token is non-empty and coins are configured.
- `fetch()` calls Hyperdash `GetPerpDeltas` once for each coin with `market` and configured `timeframe`, keeps `abs(current) >= min_delta`, deduplicates wallets globally, then calls Hyperliquid `{"type": "clearinghouseState", "user": wallet}` once per wallet.
- `HyperdashAdapter.coin_statuses` (or an equivalent service-readable status mapping) records `LIVE`, `STALE`, `ERROR`, or `NOT CONFIGURED` details per coin without raising one coin’s exception to the scheduler.

- [ ] **Step 1: Add respx tests asserting GraphQL operation/variables and filtering below-threshold deltas.** Include two coins sharing one wallet and assert only one Hyperliquid state request for that wallet.
- [ ] **Step 2: Add a test where one coin returns HTTP 500/malformed GraphQL data and another returns valid data; assert valid position events remain and the failing coin has an error status.**
- [ ] **Step 3: Add registry tests asserting an unconfigured Hyperdash adapter is skipped and a configured adapter is included alongside existing sources.**
- [ ] **Step 4: Implement GraphQL response validation, per-coin try/except isolation, wallet deduplication, and one state request per unique address.** Do not log bearer tokens; retain concise error details only.
- [ ] **Step 5: Register `HyperdashAdapter(settings)` in `build_adapters` without changing existing optional adapter behavior.**
- [ ] **Step 6: Run `uv run pytest tests/ingestion/test_hyperdash.py tests/ingestion/test_registry.py -q` and lint the touched files; expect PASS.**
- [ ] **Step 7: Commit with `git add ... && git commit -m "feat: discover Hyperdash whales per coin"`.**

### Task 3: Expose fresh per-coin positions through the dashboard service

**Files:**
- Modify: `src/hello_coin/dashboard/models.py`
- Modify: `src/hello_coin/dashboard/service.py`
- Modify: `src/hello_coin/ingestion/storage.py` only if a targeted query is needed
- Test: `tests/dashboard/test_service.py`
- Test: `tests/ingestion/test_storage.py` only if storage changes

**Interfaces:**
- Add an immutable dashboard model such as `CoinPositionTable(coin: str, rows: tuple[dict[str, Any], ...], status: SourceStatus)` and include `coin_positions: tuple[CoinPositionTable, ...]` in `DashboardSnapshot`.
- `DashboardService.load_snapshot` continues accepting the selected symbol for existing panels but also builds one table for every `settings.hyperdash_watch_coins` supplied to its constructor.
- Position rows are filtered to `source="hyperdash"`, `event_type="position"`, matching coin, and `timestamp >= now - min(2 * adapter_interval, 300 seconds)`; stale/empty/error states are explicit.

- [ ] **Step 1: Write service tests for five configured coins, a fresh LONG row with leverage/raw fields, stale rows hidden, empty rows explained, and a per-coin error status.**
- [ ] **Step 2: Run `uv run pytest tests/dashboard/test_service.py -q` and verify new tests fail.**
- [ ] **Step 3: Extend `DashboardSnapshot` with a default-safe `coin_positions` field and update all existing test fixtures/callers so backward-compatible snapshots still construct.**
- [ ] **Step 4: Extend `DashboardService` constructor with `hyperdash_watch_coins` and `position_freshness_seconds` (default derived from adapter poll interval and capped at 300), query persisted rows, parse JSON raw data, and group/filter rows per coin.**
- [ ] **Step 5: Preserve `whale_events` historical activity behavior; do not add leverage to fill rows or reuse stale position rows.**
- [ ] **Step 6: Run dashboard/service and storage tests plus `uv run ruff check` on changed files; expect PASS.**
- [ ] **Step 7: Commit with `git add ... && git commit -m "feat: expose fresh Hyperdash positions by coin"`.**

### Task 4: Render scrollable per-coin tables without console overlay

**Files:**
- Modify: `src/hello_coin/dashboard/app.py`
- Modify: `tests/dashboard/test_app.py`

**Interfaces:**
- `DashboardApp` passes Hyperdash coin configuration to `DashboardService` and keeps `r`/`q` controls and numeric symbol selection.
- `_render_snapshot` renders one scrollable widget/table per configured coin with columns `Wallet | Side | Size | Position USD | Leverage | Entry | Liquidation | uPnL | Age`.
- Formatting helpers produce `LONG`/`SHORT`, `cross · 7x` (or `7x`), truncated identifiable wallets, `N/A` for missing leverage, and explanatory empty/stale/error rows.

- [ ] **Step 1: Add Textual tests with five coin tables and assert each coin name, all required headers, a current row containing `LONG` and `7x`, and explanatory error/empty text.**
- [ ] **Step 2: Run `uv run pytest tests/dashboard/test_app.py -q` and verify new rendering assertions fail.**
- [ ] **Step 3: Replace the single whale activity panel with a scrollable per-coin container while retaining market overview, technical, bias, and system status panels.** Use Textual `DataTable`/`ScrollableContainer` with stable IDs derived from sanitized coin names.
- [ ] **Step 4: Implement rendering/formatting from `CoinPositionTable` and status state; ensure all UI logging remains routed to `data/dashboard.log` by existing CLI setup.**
- [ ] **Step 5: Run dashboard tests and a no-workers smoke test; expect PASS.**
- [ ] **Step 6: Commit with `git add ... && git commit -m "feat: render Hyperdash positions per coin"`.**

### Task 5: Wire CLI configuration, documentation, and regression coverage

**Files:**
- Modify: `src/hello_coin/cli.py` only if constructor wiring requires it
- Modify: `README.md` (or the project’s existing configuration documentation)
- Test: `tests/test_cli.py`

**Interfaces:**
- `hello-coin dashboard` remains the single command to run the 60-second dashboard; no AI or order service is started.
- Documentation lists the five Hyperdash environment variables and a safe `.env` example using placeholders, never a real token.

- [ ] **Step 1: Add a CLI regression test that invokes the dashboard construction with a settings object and confirms no `AsyncAnthropic` or decision/order code is created.**
- [ ] **Step 2: Run the focused CLI test and inspect current parser behavior.**
- [ ] **Step 3: Wire any missing settings/service arguments, add safe configuration documentation, and explicitly state Hyperdash is disabled when the token is absent.**
- [ ] **Step 4: Run `uv run pytest tests/test_cli.py tests/dashboard tests/ingestion -q`; expect PASS.**
- [ ] **Step 5: Commit with `git add ... && git commit -m "docs: document Hyperdash dashboard configuration"`.**

### Task 6: Full verification and manual terminal smoke test

**Files:**
- No source changes expected; inspect all files changed above.

- [ ] **Step 1: Run `uv run pytest` and confirm the normal offline suite passes with network tests deselected.**
- [ ] **Step 2: Run `uv run ruff check .` and fix only verified lint issues in feature files.**
- [ ] **Step 3: Run `uv run hello-coin dashboard` with no token and confirm the terminal stays usable, shows Hyperdash `NOT CONFIGURED`, does not show logs over the Textual UI, and exits cleanly with `q`.**
- [ ] **Step 4: If credentials are intentionally provided, run one controlled network smoke cycle only; never print or commit the token and do not place orders.**
- [ ] **Step 5: Review `git diff --check`, `git status --short`, and the final commit list; confirm only intended files changed and user-owned `.claude/`/`AGENTS.md` remain untouched.**

