# Terminal Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `uv run hello-coin dashboard`, a read-only Textual dashboard that starts whale and technical collection, refreshes the display every 60 seconds, and presents a deterministic market bias without AI or order placement.

**Architecture:** The `dashboard` package keeps SQLite-to-view-model transformation separate from Textual rendering. The app owns two cancellable collection workers while `DashboardService` reads persisted data and live adapter health to create immutable screen snapshots.

**Tech Stack:** Python 3.12, asyncio, SQLite, Pydantic settings, Textual, pytest, pytest-asyncio, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-29-terminal-dashboard-design.md`

## Global Constraints

- The dashboard never creates an Anthropic client, calls the decision or liquidation service, or submits an order.
- Keep all existing CLI commands unchanged.
- UI and technical collection use a 60-second interval; ingestion adapters keep their own intervals.
- Missing data is unavailable, not neutral. A failed or stale source must not close the dashboard.
- Use type annotations, four-space indentation, and 100-character lines.
- Follow test-first red-green-refactor for every behavior below.

---

### Task 1: Expose source health and newest whale events

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/base.py`
- Modify: `src/hello_coin/ingestion/storage.py`
- Modify: `tests/ingestion/test_base.py`
- Modify: `tests/ingestion/test_storage.py`

**Interfaces:**
- Produces `Adapter.last_success_at: datetime | None`, `Adapter.last_error: str | None`, and `WhaleStorage.latest_events(symbol: str, limit: int = 10) -> list[dict[str, object]]`.
- Task 2 consumes these interfaces.

- [ ] **Step 1: Write the failing adapter health test**

```python
@pytest.mark.asyncio
async def test_safe_fetch_records_success_and_clears_error():
    adapter = StubAdapter([RuntimeError("offline"), []])

    await adapter.safe_fetch()
    assert adapter.last_success_at is None
    assert adapter.last_error == "offline"

    await adapter.safe_fetch()
    assert adapter.last_success_at is not None
    assert adapter.last_error is None
```

- [ ] **Step 2: Verify the test is red**

Run: `uv run pytest tests/ingestion/test_base.py::test_safe_fetch_records_success_and_clears_error -v`

Expected: FAIL because `Adapter` has no health properties.

- [ ] **Step 3: Implement the adapter health properties**

```python
from datetime import UTC, datetime

class Adapter(ABC):
    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._disabled = False
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def last_success_at(self) -> datetime | None:
        return self._last_success_at

    @property
    def last_error(self) -> str | None:
        return self._last_error
```

In `safe_fetch`, assign `str(error)` in the exception branch. After every successful fetch,
set `datetime.now(tz=UTC)` and clear the error before returning. Preserve disable-after-five-failures behavior.

- [ ] **Step 4: Verify adapter health tests are green**

Run: `uv run pytest tests/ingestion/test_base.py -v`

Expected: PASS.

- [ ] **Step 5: Write the failing newest-events test**

```python
def test_latest_events_returns_matching_rows_newest_first_with_limit():
    storage = WhaleStorage(":memory:")
    storage.insert_events([event("old", hour=0), event("new", hour=1)])

    events = storage.latest_events("btc", limit=1)

    assert [event["dedup_key"] for event in events] == ["new"]
```

- [ ] **Step 6: Verify the storage test is red**

Run: `uv run pytest tests/ingestion/test_storage.py::test_latest_events_returns_matching_rows_newest_first_with_limit -v`

Expected: FAIL because `latest_events` does not exist.

- [ ] **Step 7: Implement the focused storage read**

```python
def latest_events(self, symbol: str, limit: int = 10) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = self._conn.execute(
        """SELECT source, timestamp, chain_or_exchange, symbol, event_type, side, amount,
                  amount_usd, wallet_address, dedup_key, raw
           FROM whale_events WHERE symbol = ? COLLATE NOCASE
           ORDER BY timestamp DESC LIMIT ?""",
        (symbol, limit),
    ).fetchall()
    return [dict(zip(_EVENT_COLUMNS, row, strict=True)) for row in rows]
```

Extract the current event column tuple into `_EVENT_COLUMNS` and reuse it in `recent_events`.
Add a test that `limit=0` raises `ValueError`.

- [ ] **Step 8: Verify all changed ingestion tests are green**

Run: `uv run pytest tests/ingestion/test_base.py tests/ingestion/test_storage.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/hello_coin/ingestion/adapters/base.py src/hello_coin/ingestion/storage.py tests/ingestion/test_base.py tests/ingestion/test_storage.py
git commit -m "feat: expose ingestion health for dashboard"
```

### Task 2: Create pure dashboard models and service

**Files:**
- Create: `src/hello_coin/dashboard/__init__.py`
- Create: `src/hello_coin/dashboard/models.py`
- Create: `src/hello_coin/dashboard/service.py`
- Create: `tests/dashboard/test_models.py`
- Create: `tests/dashboard/test_service.py`

**Interfaces:**
- Consumes Task 1 APIs, `WhaleStorage.recent_events`, `WhaleStorage.recent_metrics`, `TechnicalStorage.latest_snapshot`, `base_asset`, `compute_whale_score`, and `compute_technical_score`.
- Produces `compute_market_bias(whale_score: float | None, technical_score: float | None) -> MarketBias` and `DashboardService.load_snapshot(symbol: str, sources: Sequence[Adapter], now: datetime) -> DashboardSnapshot` for Task 3.

- [ ] **Step 1: Write failing market-bias tests**

```python
def test_market_bias_uses_approved_70_30_weights():
    bias = compute_market_bias(whale_score=1.0, technical_score=-0.5)
    assert bias.score == pytest.approx(0.55)
    assert bias.label == "BULLISH BIAS"


@pytest.mark.parametrize(
    ("whale", "technical", "label"),
    [(0.0, 0.0, "WAIT"), (-0.5, -0.5, "BEARISH BIAS"), (None, 0.8, "INSUFFICIENT DATA")],
)
def test_market_bias_thresholds_and_missing_data(whale, technical, label):
    assert compute_market_bias(whale, technical).label == label
```

- [ ] **Step 2: Verify model tests are red**

Run: `uv run pytest tests/dashboard/test_models.py -v`

Expected: FAIL because the dashboard package does not exist.

- [ ] **Step 3: Implement immutable model contracts**

```python
@dataclass(frozen=True)
class MarketBias:
    whale_score: float | None
    technical_score: float | None
    score: float | None
    label: str

def compute_market_bias(whale_score: float | None, technical_score: float | None) -> MarketBias:
    if whale_score is None or technical_score is None:
        return MarketBias(whale_score, technical_score, None, "INSUFFICIENT DATA")
    score = 0.70 * whale_score + 0.30 * technical_score
    label = "BULLISH BIAS" if score >= 0.25 else "BEARISH BIAS" if score <= -0.25 else "WAIT"
    return MarketBias(whale_score, technical_score, score, label)
```

Define frozen `SourceStatus(name, state, last_success_at, detail)` and `DashboardSnapshot`
with `symbol`, `technical`, `whale_events`, `bias`, `source_statuses`, and `refreshed_at`.

- [ ] **Step 4: Verify model tests are green**

Run: `uv run pytest tests/dashboard/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Write failing snapshot-service tests**

```python
def test_load_snapshot_includes_scores_recent_events_and_live_source():
    whale, technical = populated_storages()
    source = SimpleNamespace(
        name="binance",
        poll_interval_seconds=60,
        last_success_at=datetime(2026, 8, 29, 0, 0, tzinfo=UTC),
        last_error=None,
        disabled=False,
    )
    service = DashboardService(whale, technical, timeframe="1h", lookback_hours=24)

    snapshot = service.load_snapshot("BTCUSDT", [source], now=datetime(2026, 8, 29, 0, 1, tzinfo=UTC))

    assert snapshot.bias.label == "BULLISH BIAS"
    assert snapshot.whale_events[0]["dedup_key"] == "latest"
    assert snapshot.source_statuses[0].state == "LIVE"
```

Add three parameterized cases using the same `SimpleNamespace` shape: `last_error="offline"`
must produce `ERROR`; a success older than 120 seconds must produce `STALE`; and an empty
in-memory whale store must produce `INSUFFICIENT DATA`. Import `SimpleNamespace` from
`types`; use real in-memory storage in every case.

- [ ] **Step 6: Verify service tests are red**

Run: `uv run pytest tests/dashboard/test_service.py -v`

Expected: FAIL because `DashboardService` does not exist.

- [ ] **Step 7: Implement snapshot and source-state construction**

```python
def load_snapshot(
    self, symbol: str, sources: Sequence[Adapter], now: datetime
) -> DashboardSnapshot:
    asset = base_asset(symbol)
    since = now - timedelta(hours=self._lookback_hours)
    events = self._whale_storage.recent_events(asset, since)
    metrics = self._whale_storage.recent_metrics(symbol, since)
    metrics += self._whale_storage.recent_metrics(asset, since)
    technical = self._technical_storage.latest_snapshot(symbol, self._timeframe)
    technical_score = compute_technical_score(technical) if technical is not None else None
    bias = compute_market_bias(compute_whale_score(events, metrics), technical_score)
    source_statuses = tuple(self._source_status(source, now) for source in sources)
    return DashboardSnapshot(
        symbol=symbol,
        technical=technical,
        whale_events=tuple(self._whale_storage.latest_events(asset)),
        bias=bias,
        source_statuses=source_statuses,
        refreshed_at=now,
    )
```

Map `ERROR` when an adapter is disabled or has `last_error`; map `STALE` when it has no success or the success age exceeds twice `poll_interval_seconds`; otherwise map `LIVE`. Use the error message, `"no successful poll"`, or ISO timestamp as `detail`.

- [ ] **Step 8: Verify Task 2 tests are green**

Run: `uv run pytest tests/dashboard/test_models.py tests/dashboard/test_service.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add src/hello_coin/dashboard tests/dashboard
git commit -m "feat: add dashboard market snapshot service"
```

### Task 3: Build and test the Textual dashboard

**Files:**
- Modify: `pyproject.toml`
- Create: `src/hello_coin/dashboard/app.py`
- Create: `tests/dashboard/test_app.py`

**Interfaces:**
- Consumes Task 2 `DashboardService`, existing `Settings`, `run_ingestion_forever`, and `run_technical_forever`.
- Produces `DashboardApp(settings: Settings, adapters: list[Adapter])` for Task 4.

- [ ] **Step 1: Add the runtime dependency**

Add `"textual>=0.55.0"` to `project.dependencies` in `pyproject.toml` and run `uv sync`.

- [ ] **Step 2: Write failing headless UI tests**

```python
@pytest.mark.asyncio
async def test_dashboard_selects_second_symbol_with_two_key():
    app = DashboardApp(
        settings_with_symbols("BTCUSDT", "ETHUSDT"), adapters=[], start_workers=False
    )
    async with app.run_test() as pilot:
        await pilot.press("2")
    assert app.selected_symbol == "ETHUSDT"


@pytest.mark.asyncio
async def test_dashboard_shows_insufficient_data_without_ai_client():
    app = DashboardApp(settings_with_symbols("BTCUSDT"), adapters=[], start_workers=False)
    async with app.run_test() as pilot:
        assert "INSUFFICIENT DATA" in app.query_one("#market-bias").renderable.plain
```

Add these two tests; patch `DashboardService.load_snapshot` with `MagicMock` and use
`start_workers=False` so no network client is ever constructed:

```python
@pytest.mark.asyncio
async def test_dashboard_r_refreshes_the_current_snapshot():
    app = DashboardApp(settings_with_symbols("BTCUSDT"), adapters=[], start_workers=False)
    app._service.load_snapshot = MagicMock(return_value=insufficient_snapshot("BTCUSDT"))
    async with app.run_test() as pilot:
        await pilot.press("r")
    assert app._service.load_snapshot.call_count == 2


@pytest.mark.asyncio
async def test_dashboard_q_exits_cleanly():
    app = DashboardApp(settings_with_symbols("BTCUSDT"), adapters=[], start_workers=False)
    async with app.run_test() as pilot:
        await pilot.press("q")
    assert app.is_running is False
```

- [ ] **Step 3: Verify UI tests are red**

Run: `uv run pytest tests/dashboard/test_app.py -v`

Expected: FAIL because `DashboardApp` does not exist.

- [ ] **Step 4: Implement the app, timer, bindings, and worker cleanup**

```python
class DashboardApp(App[None]):
    BINDINGS = [("r", "refresh", "Refresh now"), ("q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.set_interval(60, self.refresh_dashboard, name="dashboard-refresh")
        if self._start_workers:
            self.run_ingestion_worker()
            self.run_technical_worker()

    def action_refresh(self) -> None:
        self.refresh_dashboard()
```

Compose `Static` widgets with IDs `market-overview`, `technical`, `market-bias`, `whale-activity`, and `system-status`. Render every panel from the same snapshot. On a SQLite exception keep prior panel content and put the error in `system-status`.

Accept `start_workers: bool = True` in `DashboardApp.__init__` and retain it as
`self._start_workers`; production callers use the default and tests pass `False`. Use two async
`@work(exit_on_error=False)` methods. The ingestion worker owns and closes
`WhaleStorage(DEFAULT_WHALE_DB_PATH)` around `run_ingestion_forever`. The technical worker owns
and closes `TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)` around
`run_technical_forever(settings.exchange_watch_symbols, settings.technical_timeframe, storage, poll_interval_seconds=60)`. Cancel workers during unmount. Bind keys
`1` through `9` for available symbols and ignore keys beyond the configured list. The footer
states that the dashboard is informational and sends no orders.

- [ ] **Step 5: Verify UI tests are green**

Run: `uv run pytest tests/dashboard/test_app.py -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add pyproject.toml uv.lock src/hello_coin/dashboard/app.py tests/dashboard/test_app.py
git commit -m "feat: add terminal dashboard application"
```

### Task 4: Integrate the CLI, document, and validate

**Files:**
- Modify: `src/hello_coin/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes `DashboardApp(settings, adapters)` from Task 3 and the existing `Settings` and `build_adapters` functions.
- Produces the user-facing `hello-coin dashboard` command.

- [ ] **Step 1: Write failing parser and dispatch tests**

```python
def test_dashboard_parses():
    assert build_parser().parse_args(["dashboard"]).command == "dashboard"


def test_main_runs_dashboard(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hello-coin", "dashboard"])
    settings = SimpleNamespace(exchange_watch_symbols=["BTCUSDT"])
    app = MagicMock()
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "build_adapters", lambda configured: [])
    monkeypatch.setattr(cli, "DashboardApp", lambda settings, adapters: app)
    cli.main()
    app.run.assert_called_once_with()
```

Import `SimpleNamespace`, `MagicMock`, and `sys`. Add `monkeypatch.setattr` for
`cli.AsyncAnthropic` that raises `AssertionError("dashboard must not create an AI client")`;
the test passes only if dashboard dispatch never evaluates that constructor.

- [ ] **Step 2: Verify CLI tests are red**

Run: `uv run pytest tests/test_cli.py::test_dashboard_parses tests/test_cli.py::test_main_runs_dashboard -v`

Expected: FAIL because the parser and runner do not exist.

- [ ] **Step 3: Implement command and runner**

```python
def _run_dashboard() -> None:
    settings = Settings()
    DashboardApp(settings=settings, adapters=build_adapters(settings)).run()
```

Register `dashboard` as a top-level parser and dispatch it before nested command branches. Import only `DashboardApp`, `Settings`, and `build_adapters` for this flow.

- [ ] **Step 4: Verify CLI tests are green**

Run: `uv run pytest tests/test_cli.py -v`

Expected: PASS, including every existing CLI parser test.

- [ ] **Step 5: Update usage documentation and ignore visual companion files**

Add this README section before `## Test`:

```markdown
## Terminal dashboard

Run `uv run hello-coin dashboard` to start local whale ingestion, technical collection, and a terminal dashboard. The display refreshes every 60 seconds and shows a deterministic market bias from whale (70%) and technical (30%) scores. It never sends orders and does not invoke the Anthropic decision engine.
```

Add `.superpowers/` to `.gitignore`. Do not add `.env`, `data/`, or generated databases to version control.

- [ ] **Step 6: Run complete validation**

Run:

```bash
uv run pytest
uv run ruff check .
uv run hello-coin --help
```

Expected: pytest has zero failures, Ruff prints `All checks passed!`, and help lists `dashboard`.

- [ ] **Step 7: Manually smoke-test without AI**

Run: `uv run hello-coin dashboard`

Expected: the Textual screen appears; unavailable optional sources are labeled rather than crashing; `r` repaints; and `q` exits without a traceback. Do not run a decision command for this test.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/hello_coin/cli.py tests/test_cli.py README.md .gitignore
git commit -m "feat: add dashboard CLI command"
```

## Plan Self-Review

- Spec coverage: Task 1 supplies live source state and display reads; Task 2 supplies deterministic scores and resilient snapshots; Task 3 supplies the 60-second Textual UI and background lifecycle; Task 4 exposes, documents, and validates the command.
- Placeholder scan: every task names its changed files, interfaces, tests, commands, expected outcomes, and implementation behavior.
- Type consistency: Task 2 consumes Task 1 APIs, Task 3 consumes Task 2 `DashboardService`, and Task 4 constructs Task 3 `DashboardApp`.
