# Whale Position Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify the local Windows desktop when a Hyperdash-discovered whale opens or closes a tracked Hyperliquid position, from the second successful refresh.

**Architecture:** A small in-memory tracker produces normalized `PositionChange` values. Hyperdash rechecks wallets from its previous snapshot before it can report a closure. The scheduler persists events and then sends the changes to an isolated Windows toast notifier.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, respx/httpx, stdlib `subprocess`, Windows PowerShell toast API.

**Spec:** `docs/superpowers/specs/2026-08-29-whale-position-notifications-design.md`

## Global Constraints

- The first successful Hyperdash refresh establishes process-local state and sends no toast.
- Only Hyperdash `position` observations can trigger notifications.
- A failed discovery or wallet-state request must never create a closure notification.
- The notifier uses local Windows functionality, logs delivery failures, and adds no credential, order API, or third-party Python dependency.
- Keep the normal offline suite green and comply with Ruff's 100-column limit.

---

## File Structure

- `src/hello_coin/ingestion/models.py`: immutable `PositionChange` model.
- `src/hello_coin/ingestion/position_changes.py`: snapshot comparison with confirmed-presence semantics.
- `src/hello_coin/ingestion/notifications.py`: notification protocol and Windows toast adapter.
- `src/hello_coin/ingestion/adapters/base.py`: no-op change consumption for all adapters.
- `src/hello_coin/ingestion/adapters/hyperdash.py`: rechecks earlier positions and exposes changes.
- `src/hello_coin/ingestion/scheduler.py`: persists events before forwarding changes.
- `src/hello_coin/cli.py`: enables notifications exclusively for ingestion services.
- `tests/ingestion/test_position_changes.py`, `test_notifications.py`, `test_hyperdash.py`, and `test_scheduler.py`: regression coverage.
- `tests/test_cli.py`: command wiring coverage.

### Task 1: Position-change model and snapshot tracker

**Files:**
- Modify: `src/hello_coin/ingestion/models.py`
- Create: `src/hello_coin/ingestion/position_changes.py`
- Test: `tests/ingestion/test_position_changes.py`

**Interfaces:**
- Produces: `PositionChange(action: Literal["open", "close"], event: WhaleEvent)`.
- Produces: `PositionChangeTracker.record(observed: dict[tuple[str, str], WhaleEvent], confirmed: set[tuple[str, str]]) -> list[PositionChange]`.

- [ ] **Step 1: Write failing baseline, open, close, and uncertain-read tests**

```python
def test_first_refresh_establishes_baseline_without_changes():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")
    assert tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")}) == []


def test_second_refresh_new_position_emits_open_change():
    tracker = PositionChangeTracker()
    tracker.record({}, set())
    event = _position("0xabc", "BTC")
    assert tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")}) == [
        PositionChange("open", event)
    ]


def test_confirmed_absence_of_prior_position_emits_close_change():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")
    tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")})
    assert tracker.record({}, {("0xabc", "BTC")}) == [PositionChange("close", event)]


def test_unconfirmed_absence_keeps_position_without_close_change():
    tracker = PositionChangeTracker()
    event = _position("0xabc", "BTC")
    tracker.record({("0xabc", "BTC"): event}, {("0xabc", "BTC")})
    assert tracker.record({}, set()) == []
```

These tests catch the defects of alerting at baseline or treating a failed
wallet request as a closed position.

- [ ] **Step 2: Verify the tests fail for the missing public interfaces**

Run: `uv run pytest tests/ingestion/test_position_changes.py -v`

Expected: collection fails because `PositionChange` and `PositionChangeTracker` are absent.

- [ ] **Step 3: Write the minimal model and tracker**

```python
@dataclass(frozen=True)
class PositionChange:
    action: Literal["open", "close"]
    event: WhaleEvent


class PositionChangeTracker:
    def record(self, observed, confirmed):
        # First call copies observations and returns no changes.
        # Later calls open unseen observed keys and close only prior confirmed keys.
```

Keep the most recent observed event per key so a later close has position
side, value, and wallet context.

- [ ] **Step 4: Verify green and lint the focused files**

Run: `uv run pytest tests/ingestion/test_position_changes.py -v; uv run ruff check src/hello_coin/ingestion/models.py src/hello_coin/ingestion/position_changes.py tests/ingestion/test_position_changes.py`

Expected: all tests pass and Ruff reports no violation.

- [ ] **Step 5: Commit the tracker**

```bash
git add src/hello_coin/ingestion/models.py src/hello_coin/ingestion/position_changes.py tests/ingestion/test_position_changes.py && git commit -m "feat: track whale position changes"
```

### Task 2: Native Windows notification boundary

**Files:**
- Create: `src/hello_coin/ingestion/notifications.py`
- Test: `tests/ingestion/test_notifications.py`

**Interfaces:**
- Consumes: `PositionChange` from Task 1.
- Produces: `NotificationSink` protocol with `notify(change: PositionChange) -> None`.
- Produces: `format_position_notification(change: PositionChange) -> tuple[str, str]` and `WindowsToastNotifier`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_open_toast_contains_action_coin_side_value_and_short_wallet():
    title, body = format_position_notification(_open_change("SOL", "sell", 125_000))
    assert title == "Whale opened position"
    assert "SOL SHORT" in body
    assert "$125,000" in body
    assert "0x1234...cdef" in body


def test_notifier_skips_non_windows_platform(monkeypatch):
    run = Mock()
    monkeypatch.setattr("hello_coin.ingestion.notifications.platform.system", lambda: "Linux")
    WindowsToastNotifier(run=run).notify(_open_change())
    run.assert_not_called()


def test_notifier_logs_delivery_failure_without_raising(monkeypatch, caplog):
    monkeypatch.setattr("hello_coin.ingestion.notifications.platform.system", lambda: "Windows")
    WindowsToastNotifier(run=Mock(side_effect=OSError("missing"))).notify(_open_change())
    assert "failed to send Windows toast" in caplog.text
```

The mutations guarded here are full wallet disclosure, wrong action/side text,
running PowerShell on non-Windows systems, and delivery errors escaping.

- [ ] **Step 2: Verify red state**

Run: `uv run pytest tests/ingestion/test_notifications.py -v`

Expected: collection fails because the notifications module does not exist.

- [ ] **Step 3: Implement safe, dependency-free toast delivery**

```python
class WindowsToastNotifier:
    def notify(self, change: PositionChange) -> None:
        if platform.system() != "Windows":
            return
        title, body = format_position_notification(change)
        try:
            self._run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                      check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError):
            logger.exception("failed to send Windows toast")
```

Build `script` from Base64-encoded JSON and escape XML text in PowerShell
before invoking `Windows.Data.Xml.Dom.XmlDocument` and
`Windows.UI.Notifications.ToastNotificationManager`. This prevents source
data from becoming PowerShell or XML syntax.

- [ ] **Step 4: Verify green and lint**

Run: `uv run pytest tests/ingestion/test_notifications.py -v; uv run ruff check src/hello_coin/ingestion/notifications.py tests/ingestion/test_notifications.py`

Expected: all tests pass and simulated delivery failure stays contained.

- [ ] **Step 5: Commit notifier support**

```bash
git add src/hello_coin/ingestion/notifications.py tests/ingestion/test_notifications.py && git commit -m "feat: add Windows whale toast notifications"
```

### Task 3: Confirmed Hyperdash position changes

**Files:**
- Modify: `src/hello_coin/ingestion/adapters/base.py`
- Modify: `src/hello_coin/ingestion/adapters/hyperdash.py`
- Modify: `tests/ingestion/test_base.py`
- Modify: `tests/ingestion/test_hyperdash.py`

**Interfaces:**
- Consumes: `PositionChangeTracker` from Task 1.
- Produces: `Adapter.consume_position_changes() -> list[PositionChange]`, returning `[]` by default.
- Produces: `HyperdashAdapter.consume_position_changes() -> list[PositionChange]`, clearing its pending changes after each call.

- [ ] **Step 1: Write failing sequential Hyperdash tests**

```python
@pytest.mark.asyncio
@respx.mock
async def test_second_refresh_reports_open_after_silent_baseline():
    await adapter.fetch()  # no qualifying position
    assert adapter.consume_position_changes() == []
    await adapter.fetch()  # qualifying LINK position
    assert [(change.action, change.event.symbol)] == [("open", "LINK")]


@pytest.mark.asyncio
@respx.mock
async def test_prior_wallet_is_rechecked_and_confirmed_close_is_reported():
    await adapter.fetch()  # LINK position for wallet
    await adapter.fetch()  # delta omits wallet; state response has no LINK position
    assert [(change.action, change.event.wallet_address)] == [("close", wallet)]
    assert state.call_count == 2
```

Add a third test where the prior wallet's second state request returns HTTP
500 and assert no close is emitted. This detects relying only on fresh delta
candidates or turning a failed recheck into a closure.

- [ ] **Step 2: Verify Hyperdash tests fail**

Run: `uv run pytest tests/ingestion/test_hyperdash.py tests/ingestion/test_base.py -v`

Expected: failure because adapters cannot consume changes and prior wallets are not rechecked.

- [ ] **Step 3: Implement the no-op base boundary and confirmed rechecks**

Add a no-op `consume_position_changes` method to `Adapter`. In
`HyperdashAdapter`, retain a `PositionChangeTracker` and a pending change
list. For each coin whose GraphQL discovery succeeds, combine qualifying
addresses with previously active wallets for that coin and fetch every unique
wallet once. For new addresses, accept only positions meeting the configured
minimum; for a tracked position, preserve any non-zero current position even
if its value fell below the threshold. Mark a key confirmed only after its
wallet state fetch succeeds, pass observations and confirmations to the
tracker, and return-and-clear pending changes from the consume method.

- [ ] **Step 4: Verify focused integration tests and lint**

Run: `uv run pytest tests/ingestion/test_hyperdash.py tests/ingestion/test_base.py -v; uv run ruff check src/hello_coin/ingestion/adapters/base.py src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py tests/ingestion/test_base.py`

Expected: all existing filtering/error-isolation tests and new change tests pass.

- [ ] **Step 5: Commit adapter change production**

```bash
git add src/hello_coin/ingestion/adapters/base.py src/hello_coin/ingestion/adapters/hyperdash.py tests/ingestion/test_hyperdash.py tests/ingestion/test_base.py && git commit -m "feat: detect Hyperdash whale position changes"
```

### Task 4: Scheduler dispatch and ingestion activation

**Files:**
- Modify: `src/hello_coin/ingestion/scheduler.py`
- Modify: `src/hello_coin/cli.py`
- Modify: `tests/ingestion/test_scheduler.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Adapter.consume_position_changes` and `NotificationSink`.
- Produces: `poll_once(adapter, storage, notifier: NotificationSink | None = None) -> int`.
- Produces: `run_forever(adapters, storage, notifier: NotificationSink | None = None) -> None`.

- [ ] **Step 1: Write failing scheduler and CLI tests**

```python
@pytest.mark.asyncio
async def test_poll_once_notifies_changes_after_persisting_events():
    storage = WhaleStorage(":memory:")
    adapter = _FixedResultAdapter([_event("new")])
    adapter.changes = [PositionChange("open", _event("new"))]
    notifier = RecordingNotifier(storage)
    assert await poll_once(adapter, storage, notifier) == 1
    assert notifier.event_count_when_called == 1


@pytest.mark.asyncio
async def test_poll_once_logs_notifier_failure_and_returns_insert_count(caplog):
    # A notifier raising RuntimeError must not escape poll_once.
```

In `tests/test_cli.py`, patch `WindowsToastNotifier` and
`run_ingestion_forever`, run `_run_ingest()` using an immediately returning
coroutine, and assert the created notifier is passed to the ingestion runner.
Retain the dashboard test proving that dashboard creates no extra service.

- [ ] **Step 2: Verify scheduler and CLI tests fail**

Run: `uv run pytest tests/ingestion/test_scheduler.py tests/test_cli.py -v`

Expected: failure because scheduler calls lack `notifier` and CLI does not construct one.

- [ ] **Step 3: Persist first, then dispatch safely; wire only ingestion**

```python
async def poll_once(adapter, storage, notifier=None):
    result = await adapter.safe_fetch()
    inserted = storage.insert_events(result) if result and isinstance(result[0], WhaleEvent) else ...
    if notifier:
        for change in adapter.consume_position_changes():
            try:
                notifier.notify(change)
            except Exception:
                logger.exception("failed to deliver whale position notification")
    return inserted
```

Pass this optional notifier through `run_adapter_loop` and `run_forever`.
Instantiate `WindowsToastNotifier()` in `_run_ingest` only; do not change
`_run_dashboard` or add notification behavior to the dashboard.

- [ ] **Step 4: Verify green and lint**

Run: `uv run pytest tests/ingestion/test_scheduler.py tests/test_cli.py -v; uv run ruff check src/hello_coin/ingestion/scheduler.py src/hello_coin/cli.py tests/ingestion/test_scheduler.py tests/test_cli.py`

Expected: all tests pass, stored events precede the notifier call, and notifier errors are logged.

- [ ] **Step 5: Commit command activation**

```bash
git add src/hello_coin/ingestion/scheduler.py src/hello_coin/cli.py tests/ingestion/test_scheduler.py tests/test_cli.py && git commit -m "feat: notify whale position changes during ingestion"
```

### Task 5: Full regression verification

**Files:**
- Modify: no source file expected
- Test: full offline suite

**Interfaces:**
- Verifies Tasks 1–4 together.

- [ ] **Step 1: Run the complete offline suite**

Run: `uv run pytest`

Expected: exit code 0; existing network marker keeps live API tests excluded.

- [ ] **Step 2: Run full lint**

Run: `uv run ruff check .`

Expected: exit code 0 with no Ruff violations.

- [ ] **Step 3: Inspect the final feature scope**

Run: `git diff HEAD~4..HEAD -- src/hello_coin tests pyproject.toml`

Expected: no credentials, order APIs, dashboard notifications, or package dependency.

## Plan Self-Review

- Task 1 covers first-refresh silence, opens, confirmed closes, and uncertainty.
- Task 2 covers native notification content and safe platform/delivery failures.
- Task 3 covers rechecking previously active wallets and adapter isolation.
- Task 4 covers persistence ordering, scheduler containment, and CLI-only activation.
- Task 5 verifies the full offline suite, linting, and safety scope.
