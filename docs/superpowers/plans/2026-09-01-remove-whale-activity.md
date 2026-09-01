# Remove Whale Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the whale-activity feature (adapters, whale scoring, whale weighting) while keeping the hyperdash position-skew pipeline, its dashboard charts, and Telegram alerts.

**Architecture:** Pure removal plus re-weighting. The `ingestion` package shrinks to the hyperdash adapter + skew storage; `decision` drops `whale_score` and re-weights to technical 60% / liquidation 40% (technical 100% when liquidation is missing); the dashboard loses the whale-events panel and derives bias from technical only. `base_asset()` moves to `src/hello_coin/symbols.py` because both dashboard and decision still need it.

**Tech Stack:** Python 3.12, uv, pytest, ruff, SQLite, FastAPI/Jinja2.

Spec: `docs/superpowers/specs/2026-09-01-remove-whale-activity-design.md`

---

### Task 1: Delete whale adapters and slim the registry

**Files:**
- Delete: `src/hello_coin/ingestion/adapters/{binance,okx,bybit,bitget,etherscan,cryptoquant,debank,nansen,whale_alert,bitquery,hyperliquid}.py`
- Delete: `tests/ingestion/test_{binance,okx,bybit,bitget,exchange_smoke,etherscan,cryptoquant,debank,nansen,whale_alert,bitquery,hyperliquid,hyperliquid_smoke}.py`
- Modify: `src/hello_coin/ingestion/registry.py`
- Modify: `tests/ingestion/test_registry.py` (keep only hyperdash expectations)

- [ ] **Step 1:** Delete the 11 adapter files and 13 test files listed above (`git rm`).
- [ ] **Step 2:** Rewrite `registry.py`:

```python
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.hyperdash import HyperdashAdapter
from hello_coin.ingestion.config import Settings

logger = logging.getLogger(__name__)


def build_adapters(settings: Settings) -> list[Adapter]:
    """Return every adapter that reports itself as configured, logging a
    warning for each one that's skipped."""

    candidates: list[Adapter] = [HyperdashAdapter(settings)]

    configured: list[Adapter] = []
    for adapter in candidates:
        if adapter.is_configured():
            configured.append(adapter)
        else:
            logger.warning("%s: not configured, skipping", adapter.name)
    return configured
```

- [ ] **Step 3:** Update `tests/ingestion/test_registry.py`: remove tests referencing deleted adapters; keep/add a test that a fully-unset `Settings` yields only whatever hyperdash's `is_configured()` allows, and that a hyperdash-configured `Settings` yields exactly `["hyperdash"]`.
- [ ] **Step 4:** Run `uv run pytest tests/ingestion/ -x` — expect failures only in files touched by later tasks (config/models/storage/base/scheduler may still pass here; fix registry-related failures now).
- [ ] **Step 5:** Commit: `refactor: drop whale adapters, registry is hyperdash-only`

### Task 2: Strip removed-adapter settings from config

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `.env.example`
- Modify: `tests/ingestion/test_config.py`

- [ ] **Step 1:** In `Settings`, delete these fields: `hyperliquid_watch_addresses`, `etherscan_api_key`, `etherscan_watch_addresses`, `debank_access_key`, `debank_watch_addresses`, `cryptoquant_api_key`, `nansen_api_key`, `nansen_watch_addresses`, `whale_alert_api_key`, `whale_alert_min_value_usd`, `bitquery_access_token`, `bitquery_min_value_usd`, `decision_whale_lookback_hours`. Trim the `field_validator` list to `exchange_watch_symbols`, `hyperdash_watch_coins`. Update the class docstring (credentials-optional wording now applies to hyperdash/telegram/coinglass/anthropic only).
- [ ] **Step 2:** Remove the same variables from `.env.example`.
- [ ] **Step 3:** Update `tests/ingestion/test_config.py` to drop assertions on deleted fields.
- [ ] **Step 4:** `uv run pytest tests/ingestion/test_config.py -v` → PASS.
- [ ] **Step 5:** Commit: `refactor: remove whale-adapter settings from config`

### Task 3: Remove WhaleMetric from models, storage, base, scheduler

**Files:**
- Modify: `src/hello_coin/ingestion/models.py` (delete the `WhaleMetric` dataclass)
- Modify: `src/hello_coin/ingestion/storage.py`
- Modify: `src/hello_coin/ingestion/adapters/base.py` (fetch result type loses `WhaleMetric`)
- Modify: `src/hello_coin/ingestion/scheduler.py` (drop metric persistence branch if present)
- Modify: `tests/ingestion/test_models.py`, `test_storage.py`, `test_base.py`, `test_scheduler.py`

- [ ] **Step 1:** Delete `WhaleMetric` from `models.py`.
- [ ] **Step 2:** In `storage.py` delete: `_METRICS_SCHEMA`, `_METRICS_SYMBOL_INDEX`, `insert_metrics()`, `recent_metrics()`, the `WhaleMetric` import, and the two `self._conn.execute` calls for metrics schema/index in `__init__`. Do NOT drop the `whale_metrics` table from existing DBs (no destructive migration). Events + skew code unchanged.
- [ ] **Step 3:** In `base.py` and `scheduler.py`, remove `WhaleMetric` from imports and type unions; the fetch result is now `WhaleEvent`/`SkewSnapshot`/`SkewAlert` items only. Follow the existing union style in `base.py`.
- [ ] **Step 4:** Update the four test files: delete metric-specific tests; adjust type assertions.
- [ ] **Step 5:** `uv run pytest tests/ingestion/ -v` → PASS.
- [ ] **Step 6:** Commit: `refactor: drop WhaleMetric from ingestion models/storage`

### Task 4: Move base_asset to a shared module, delete whale_score

**Files:**
- Create: `src/hello_coin/symbols.py`
- Create: `tests/test_symbols.py`
- Delete: `src/hello_coin/decision/whale_score.py`, `tests/decision/test_whale_score.py`
- Modify: `src/hello_coin/decision/service.py`, `src/hello_coin/dashboard/service.py` (imports only, full rework in Tasks 5–6)

- [ ] **Step 1:** Create `src/hello_coin/symbols.py`:

```python
_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


def base_asset(symbol: str) -> str:
    """Strip a quote suffix ("BTCUSDT" -> "BTC") to bridge symbol conventions."""
    upper = symbol.upper()
    for suffix in _QUOTE_SUFFIXES:
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]
    return upper
```

- [ ] **Step 2:** Create `tests/test_symbols.py` (port the `base_asset` cases from `tests/decision/test_whale_score.py`):

```python
from hello_coin.symbols import base_asset


def test_base_asset_strips_usdt():
    assert base_asset("BTCUSDT") == "BTC"


def test_base_asset_strips_usd():
    assert base_asset("ethusd") == "ETH"


def test_base_asset_leaves_plain_symbol():
    assert base_asset("HYPE") == "HYPE"


def test_base_asset_does_not_strip_whole_symbol():
    assert base_asset("USDT") == "USDT"
```

- [ ] **Step 3:** Delete `whale_score.py` and `test_whale_score.py`; point `decision/service.py` and `dashboard/service.py` imports at `hello_coin.symbols` (their `compute_whale_score` usages are removed in Tasks 5–6 — this task may leave them temporarily broken only if executed standalone; execute Tasks 4–6 in one sitting).
- [ ] **Step 4:** `uv run pytest tests/test_symbols.py -v` → PASS.
- [ ] **Step 5:** Commit together with Task 5 if the tree is not green in between.

### Task 5: Re-weight the decision engine (technical 60 / liquidation 40)

**Files:**
- Modify: `src/hello_coin/decision/service.py`, `models.py`, `storage.py`, `scheduler.py`
- Modify: `src/hello_coin/cli.py` (`_run_decision`, `_test_decision` drop whale storage/lookback)
- Modify: `tests/decision/test_service.py`, `test_models.py`, `test_storage.py`, `test_scheduler.py`

- [ ] **Step 1:** `models.py`: delete the `whale_score` field from `Decision`.
- [ ] **Step 2:** `storage.py`: keep the `whale_score` column in `_SCHEMA` (legacy, nullable) but insert `None` for it; remove `decision.whale_score` from the insert tuple, passing `None` in its place.
- [ ] **Step 3:** `service.py`: drop `whale_storage`, `whale_lookback_hours`, `base_asset` usage and the events/metrics reads from `compute_decision`; new weighting block:

```python
if technical_score is not None and liquidation_score is not None:
    weighted_score = 0.60 * technical_score + 0.40 * liquidation_score
elif technical_score is not None:
    weighted_score = technical_score
else:
    weighted_score = None
```

New `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = (
    "You are a crypto trading decision assistant for the hello-coin system. Technical "
    "indicators and the liquidation heatmap are combined into weighted_score: when both "
    "signals are available, technical carries 60% and liquidation 40% of the weight; when "
    "the liquidation signal is unavailable, the technical score carries 100% — treat "
    "weighted_score's value as authoritative rather than assuming a fixed split. Scores "
    "range from -1 (strongly bearish) to +1 (strongly bullish); a missing score means that "
    "data source had nothing usable this cycle, not that it's neutral — factor the gap into "
    "your confidence rather than ignoring it. When liquidation cluster prices are provided, "
    "use them as concrete levels for entry/exit timing and stop-loss/take-profit placement, "
    "not just for direction. Always call the decide tool."
)
```

`_build_user_message` drops the `whale_score` line and parameter.
- [ ] **Step 4:** `scheduler.py`: remove `whale_storage` and `whale_lookback_hours` parameters from `poll_once`, `run_symbol_loop`, `run_forever` and their pass-through call sites.
- [ ] **Step 5:** `cli.py`: `_run_decision`/`_test_decision` stop constructing `WhaleStorage` and stop passing `whale_lookback_hours` (the setting was deleted in Task 2).
- [ ] **Step 6:** Update decision tests: delete whale-score fixtures/params; assert the new weighting (e.g. technical=0.5, liquidation=-0.5 → weighted 0.10; technical-only 0.5 → 0.5; technical missing → None).
- [ ] **Step 7:** `uv run pytest tests/decision/ tests/test_cli.py -v` → PASS.
- [ ] **Step 8:** Commit: `feat!: decision engine drops whale signal, technical 60/liquidation 40`

### Task 6: Dashboard — remove whale panel, technical-only bias

**Files:**
- Modify: `src/hello_coin/dashboard/models.py`, `service.py`, `web.py`
- Modify: `src/hello_coin/dashboard/templates/_panels.html` (and `page.html` if it references removed blocks)
- Modify: `src/hello_coin/dashboard/formatting.py` (remove helpers only if now unused — check template usage first; position tables still use wallet/leverage formatters)
- Modify: `tests/dashboard/test_models.py`, `test_service.py`, `test_web.py`, `test_formatting.py`

- [ ] **Step 1:** `models.py`: `MarketBias` drops `whale_score`; `DashboardSnapshot` drops `whale_events`; `compute_market_bias` becomes technical-only:

```python
def compute_market_bias(technical_score: float | None) -> MarketBias:
    if technical_score is None:
        return MarketBias(technical_score=None, score=None, label="INSUFFICIENT DATA")
    score = technical_score
    if score >= 0.25:
        label = "BULLISH BIAS"
    elif score <= -0.25:
        label = "BEARISH BIAS"
    else:
        label = "WAIT"
    return MarketBias(technical_score=technical_score, score=score, label=label)
```

- [ ] **Step 2:** `service.py`: `load_snapshot` drops `recent_events`/`recent_metrics`/`latest_events`/`compute_whale_score` and the `lookback_hours` constructor param; keeps `_load_coin_positions` (which reads hyperdash position events + skew history) unchanged; `bias = compute_market_bias(technical_score)`.
- [ ] **Step 3:** `web.py`: stop passing `lookback_hours=settings.decision_whale_lookback_hours` to `DashboardService` (setting deleted in Task 2).
- [ ] **Step 4:** `_panels.html`: delete the `whale-activity` panel block and the `whale_event_item` macro; in the `market-bias` panel replace the Whale/Technical line with `Technical: {{ format_number(snapshot.bias.technical_score) }}`. Remove now-unused formatting helpers and their template globals in `web.py` ONLY if `grep` shows no remaining use in either template.
- [ ] **Step 5:** Update dashboard tests to the new signatures; delete whale-events assertions.
- [ ] **Step 6:** `uv run pytest tests/dashboard/ -v` → PASS.
- [ ] **Step 7:** Commit: `feat!: dashboard drops whale-activity panel, bias is technical-only`

### Task 7: CLI wording and docs

**Files:**
- Modify: `src/hello_coin/cli.py` (help strings: "whale ingestion" → "position-skew ingestion"; `ingest test` example `hyperliquid` → `hyperdash`)
- Modify: `CLAUDE.md` (product intent: technical 60 / liquidation 40, fallback technical 100; architecture section: ingestion = hyperdash skew pipeline; remove deleted adapter/whale_score references)
- Modify: `tests/test_cli.py` if it asserts help text

- [ ] **Step 1:** Apply the wording changes.
- [ ] **Step 2:** `uv run pytest` (full suite) → PASS; `uv run ruff check .` → clean.
- [ ] **Step 3:** Commit: `docs: update CLAUDE.md and CLI help for whale removal`

### Task 8: Rebuild and verify the running dashboard

- [ ] **Step 1:** `docker compose build` → image builds.
- [ ] **Step 2:** `docker compose up -d` → container healthy; `curl http://localhost:8080/` returns the dashboard with skew charts and no whale panel.
- [ ] **Step 3:** Report to the owner for visual review.
