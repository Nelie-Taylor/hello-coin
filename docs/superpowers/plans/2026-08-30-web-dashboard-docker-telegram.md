# Web Dashboard, Docker Deployment, Telegram Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Textual terminal dashboard with a FastAPI web dashboard reachable over HTTP, replace `WindowsToastNotifier` with a Telegram bot notifier, and package the dashboard (web UI + whale ingestion + technical indicators) to run in Docker.

**Architecture:** `DashboardService`/`DashboardSnapshot` (data layer) are untouched. A new `src/hello_coin/dashboard/web.py` FastAPI app renders the same snapshot data as server-rendered Jinja2 HTML, polled every 60s via a vendored HTMX script instead of Textual's `@work` loop. `TelegramNotifier` in `src/hello_coin/ingestion/notifications.py` replaces `WindowsToastNotifier` behind the same `NotificationSink` protocol (now `async`). A `Dockerfile` + `docker-compose.yml` run `hello-coin dashboard` in a container with `./data` mounted as a volume.

**Tech Stack:** FastAPI, Jinja2, uvicorn, HTMX (vendored static file), httpx (Telegram Bot API), pytest/pytest-asyncio/respx (existing), Docker/docker-compose.

Full design: `docs/superpowers/specs/2026-08-30-web-dashboard-docker-telegram-design.md`

---

### Task 1: Add web framework dependencies

**Files:**
- Modify: `pyproject.toml:10-15`

- [ ] **Step 1: Add fastapi, jinja2, uvicorn to dependencies**

In `pyproject.toml`, change:

```toml
dependencies = [
    "anthropic>=1.0.0",
    "httpx>=0.28.1",
    "pydantic-settings>=2.15.0",
    "textual>=0.55.0",
]
```

to:

```toml
dependencies = [
    "anthropic>=1.0.0",
    "fastapi>=0.115.0",
    "httpx>=0.28.1",
    "jinja2>=3.1.4",
    "pydantic-settings>=2.15.0",
    "textual>=0.55.0",
    "uvicorn>=0.34.0",
]
```

(`textual` stays for now — it's removed in Task 7 once nothing imports it anymore.)

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`
Expected: resolves and installs `fastapi`, `jinja2`, `uvicorn` (and their transitive deps) without error; `uv.lock` is updated.

- [ ] **Step 3: Confirm the existing suite still passes**

Run: `uv run pytest`
Expected: PASS (no behavior changed yet, this only adds unused-so-far dependencies).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add fastapi, jinja2, uvicorn dependencies"
```

---

### Task 2: Telegram and dashboard-server settings

**Files:**
- Modify: `src/hello_coin/ingestion/config.py:40-42`
- Test: `tests/ingestion/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_config.py`:

```python
def test_telegram_and_dashboard_settings_default(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_HOST", "DASHBOARD_PORT"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token is None
    assert settings.telegram_chat_id is None
    assert settings.dashboard_host == "0.0.0.0"
    assert settings.dashboard_port == 8080


def test_telegram_and_dashboard_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("DASHBOARD_PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token == "bot-token"
    assert settings.telegram_chat_id == "12345"
    assert settings.dashboard_host == "127.0.0.1"
    assert settings.dashboard_port == 9000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'telegram_bot_token'`

- [ ] **Step 3: Add the fields**

In `src/hello_coin/ingestion/config.py`, after the `liquidation_poll_interval_seconds` line, add:

```python
    coinglass_api_key: str | None = None
    liquidation_proximity_pct: float = 0.10
    liquidation_poll_interval_seconds: int = 900

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/config.py tests/ingestion/test_config.py
git commit -m "feat: add Telegram and dashboard-server settings"
```

---

### Task 3: Dashboard formatting helpers

Pulls the `@staticmethod` formatting helpers out of the old Textual `DashboardApp` into a
standalone, framework-free module the Jinja templates can call directly as filters/globals.

**Files:**
- Create: `src/hello_coin/dashboard/formatting.py`
- Test: `tests/dashboard/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/dashboard/test_formatting.py`:

```python
from datetime import UTC, datetime

from hello_coin.dashboard.formatting import (
    coin_panel_id,
    format_age,
    format_direction,
    format_event_leverage,
    format_number,
    format_position_leverage,
    format_wallet,
    position_side_label,
)


def test_format_number_handles_none_and_floats():
    assert format_number(None) == "unavailable"
    assert format_number(1234.5) == "1,234.5000"


def test_format_number_passes_through_strings():
    assert format_number("BTCUSDT") == "BTCUSDT"


def test_format_wallet_truncates_long_addresses():
    assert format_wallet("0x1234567890abcdef") == "0x12345…bcdef"
    assert format_wallet(None) == "N/A"


def test_format_age_computes_seconds_since_timestamp():
    now = datetime(2026, 8, 29, 0, 1, tzinfo=UTC)
    assert format_age("2026-08-29T00:00:30+00:00", now) == "30s"
    assert format_age(None, now) == "N/A"


def test_format_direction_maps_buy_and_sell():
    assert format_direction("buy") == "LONG (BUY)"
    assert format_direction("sell") == "SHORT (SELL)"
    assert format_direction(None) == "N/A"


def test_format_event_leverage_reads_nested_and_string_raw():
    assert format_event_leverage('{"leverage": {"type": "cross", "value": 7}}') == "7x"
    assert format_event_leverage("{}") == "N/A"
    assert format_event_leverage("not json") == "N/A"


def test_format_position_leverage_combines_type_and_value():
    assert format_position_leverage({"leverage": {"type": "cross", "value": 7}}) == "cross · 7x"
    assert format_position_leverage({}) == "N/A"


def test_position_side_label_maps_buy_and_sell():
    assert position_side_label("buy") == "LONG"
    assert position_side_label("sell") == "SHORT"
    assert position_side_label("other") == "N/A"


def test_coin_panel_id_slugifies_symbol():
    assert coin_panel_id("LINK") == "coin-link"
    assert coin_panel_id("BTC-PERP") == "coin-btc-perp"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.dashboard.formatting'`

- [ ] **Step 3: Implement the module**

Create `src/hello_coin/dashboard/formatting.py`:

```python
"""Pure, framework-free formatting helpers shared by the dashboard templates."""

import json
from datetime import datetime


def format_number(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, int | float):
        return f"{value:,.4f}"
    return str(value)


def format_wallet(value: object) -> str:
    text = str(value or "N/A")
    return text if len(text) <= 14 else f"{text[:7]}…{text[-5:]}"


def format_age(value: object, now: datetime) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value))
        return f"{max(0, int((now - timestamp).total_seconds()))}s"
    except (TypeError, ValueError):
        return "N/A"


def format_direction(side: object) -> str:
    if side == "buy":
        return "LONG (BUY)"
    if side == "sell":
        return "SHORT (SELL)"
    return "N/A"


def format_event_leverage(raw: object) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return "N/A"
    if not isinstance(raw, dict):
        return "N/A"
    leverage = raw.get("leverage")
    if isinstance(leverage, dict):
        leverage = leverage.get("value")
    if isinstance(leverage, int | float):
        return f"{leverage:g}x"
    return "N/A"


def format_position_leverage(raw: object) -> str:
    if not isinstance(raw, dict):
        return "N/A"
    leverage = raw.get("leverage")
    if not isinstance(leverage, dict):
        return "N/A"
    value = leverage.get("value")
    if not isinstance(value, int | float):
        return "N/A"
    kind = leverage.get("type")
    return f"{kind} · {value:g}x" if kind else f"{value:g}x"


def position_side_label(side: object) -> str:
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    return "N/A"


def coin_panel_id(coin: str) -> str:
    return "coin-" + "".join(character.lower() if character.isalnum() else "-" for character in coin)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_formatting.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/dashboard/formatting.py tests/dashboard/test_formatting.py
git commit -m "feat: extract dashboard formatting helpers into a standalone module"
```

---

### Task 4: Telegram notifications

Replaces `WindowsToastNotifier` with `TelegramNotifier` and makes `NotificationSink.notify`
`async` end-to-end (notifier → `scheduler.poll_once` → its one caller, `cli._run_ingest`).

**Files:**
- Modify: `src/hello_coin/ingestion/notifications.py` (full rewrite)
- Modify: `src/hello_coin/ingestion/scheduler.py:25-30`
- Modify: `src/hello_coin/cli.py:13,96`
- Test: `tests/ingestion/test_notifications.py` (full rewrite)
- Test: `tests/ingestion/test_scheduler.py:94-131`

- [ ] **Step 1: Write the failing tests for TelegramNotifier**

Replace all of `tests/ingestion/test_notifications.py` with:

```python
import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from hello_coin.ingestion.models import PositionChange, WhaleEvent
from hello_coin.ingestion.notifications import TelegramNotifier, format_position_notification


def _change(action: str = "open") -> PositionChange:
    return PositionChange(
        action=action,  # type: ignore[arg-type]
        event=WhaleEvent(
            source="hyperdash",
            timestamp=datetime(2026, 8, 29, tzinfo=UTC),
            chain_or_exchange="hyperliquid",
            symbol="SOL",
            event_type="position",
            side="sell",
            amount=5.0,
            amount_usd=125_000.0,
            wallet_address="0x1234567890abcdef",
            dedup_key="position:test",
        ),
    )


def test_open_notification_contains_action_coin_side_value_and_short_wallet():
    title, body = format_position_notification(_change())

    assert title == "Whale opened position"
    assert "SOL SHORT" in body
    assert "$125,000" in body
    assert "0x1234...cdef" in body


@pytest.mark.asyncio
@respx.mock
async def test_notify_posts_title_and_body_to_telegram_api():
    route = respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_change())

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "chat456"
    assert "Whale opened position" in payload["text"]
    assert "SOL SHORT" in payload["text"]


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_bot_token():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier(None, "chat456", client=client)
        await notifier.notify(_change())


@pytest.mark.asyncio
@respx.mock
async def test_notify_is_noop_without_chat_id():
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", None, client=client)
        await notifier.notify(_change())


@pytest.mark.asyncio
@respx.mock
async def test_notify_logs_delivery_failure_without_raising(caplog):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as client:
        notifier = TelegramNotifier("token123", "chat456", client=client)
        await notifier.notify(_change())

    assert "failed to send Telegram notification" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_notifications.py -v`
Expected: FAIL with `ImportError: cannot import name 'TelegramNotifier'`

- [ ] **Step 3: Rewrite the notifications module**

Replace all of `src/hello_coin/ingestion/notifications.py` with:

```python
import logging
from typing import Protocol

import httpx

from hello_coin.ingestion.models import PositionChange

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationSink(Protocol):
    async def notify(self, change: PositionChange) -> None: ...


def _short_wallet(wallet: str | None) -> str:
    if not wallet:
        return "unknown wallet"
    if len(wallet) <= 10:
        return wallet
    return f"{wallet[:6]}...{wallet[-4:]}"


def format_position_notification(change: PositionChange) -> tuple[str, str]:
    event = change.event
    action = "opened" if change.action == "open" else "closed"
    side = {"buy": "LONG", "sell": "SHORT"}.get(event.side, "UNKNOWN")
    value = f"${event.amount_usd:,.0f}" if event.amount_usd is not None else "value unavailable"
    return f"Whale {action} position", f"{event.symbol} {side} · {value} · {_short_wallet(event.wallet_address)}"


class TelegramNotifier:
    """Deliver whale position-change alerts via the Telegram Bot API.

    A missing bot token or chat ID is treated as "not configured" — `notify()` is a
    silent no-op, matching every other optional credential in this codebase.
    """

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def notify(self, change: PositionChange) -> None:
        if not self._bot_token or not self._chat_id:
            return
        title, body = format_position_notification(change)
        try:
            response = await self._client.post(
                TELEGRAM_API_URL.format(token=self._bot_token),
                json={"chat_id": self._chat_id, "text": f"{title}\n{body}"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("failed to send Telegram notification")
```

- [ ] **Step 4: Run notification tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_notifications.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Update the failing scheduler tests to await notify()**

`notifier.notify()` is now a coroutine. In `tests/ingestion/test_scheduler.py`, the two inline
notifier classes inside the test bodies must become `async def notify`. Change:

```python
    class _Notifier:
        def __init__(self) -> None:
            self.count_when_notified = 0
            self.changes: list[PositionChange] = []

        def notify(self, change: PositionChange) -> None:
            self.count_when_notified = storage.count_events()
            self.changes.append(change)
```

to:

```python
    class _Notifier:
        def __init__(self) -> None:
            self.count_when_notified = 0
            self.changes: list[PositionChange] = []

        async def notify(self, change: PositionChange) -> None:
            self.count_when_notified = storage.count_events()
            self.changes.append(change)
```

and change:

```python
    class _FailingNotifier:
        def notify(self, change: PositionChange) -> None:
            raise RuntimeError("toast unavailable")
```

to:

```python
    class _FailingNotifier:
        async def notify(self, change: PositionChange) -> None:
            raise RuntimeError("toast unavailable")
```

- [ ] **Step 6: Run scheduler tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: FAIL — `test_poll_once_notifies_changes_after_persisting_events` and
`test_poll_once_logs_notifier_failure_and_returns_insert_count` fail because
`poll_once` still calls `notifier.notify(change)` without `await`, so the coroutine is
never actually run (the assertions on `notifier.changes`/`caplog` don't see the effects).

- [ ] **Step 7: Await notify() in poll_once**

In `src/hello_coin/ingestion/scheduler.py`, change:

```python
    if notifier is not None:
        for change in adapter.consume_position_changes():
            try:
                notifier.notify(change)
            except Exception:
                logger.exception("failed to deliver whale position notification")
```

to:

```python
    if notifier is not None:
        for change in adapter.consume_position_changes():
            try:
                await notifier.notify(change)
            except Exception:
                logger.exception("failed to deliver whale position notification")
```

- [ ] **Step 8: Run scheduler tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_scheduler.py -v`
Expected: PASS (6 tests)

- [ ] **Step 9: Wire TelegramNotifier into the CLI's ingest command**

In `src/hello_coin/cli.py`, change the import:

```python
from hello_coin.ingestion.notifications import WindowsToastNotifier
```

to:

```python
from hello_coin.ingestion.notifications import TelegramNotifier
```

and in `_run_ingest()`, change:

```python
    notifier = WindowsToastNotifier()
```

to:

```python
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
```

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest`
Expected: PASS (only `tests/dashboard/test_app.py` is unaffected by this task; it still uses
the not-yet-removed Textual app)

- [ ] **Step 11: Commit**

```bash
git add src/hello_coin/ingestion/notifications.py src/hello_coin/ingestion/scheduler.py \
  src/hello_coin/cli.py tests/ingestion/test_notifications.py tests/ingestion/test_scheduler.py
git commit -m "feat: replace Windows Toast whale alerts with Telegram"
```

---

### Task 5: Web dashboard static assets and templates

Content-only task (HTML/CSS/JS) — verified by the FastAPI route tests in Task 6, not by
standalone unit tests.

**Files:**
- Create: `src/hello_coin/dashboard/static/dashboard.css`
- Create: `src/hello_coin/dashboard/static/dashboard.js`
- Create: `src/hello_coin/dashboard/static/htmx.min.js` (vendored, not hand-written)
- Create: `src/hello_coin/dashboard/templates/page.html`
- Create: `src/hello_coin/dashboard/templates/_panels.html`

- [ ] **Step 1: Vendor HTMX so the container works with no outbound internet access**

Run:

```bash
curl -L -o src/hello_coin/dashboard/static/htmx.min.js https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
```

Expected: the file is created and is at least 30KB. Verify with:

```bash
wc -c src/hello_coin/dashboard/static/htmx.min.js
```

Expected: a byte count over 30000. If there's no network access in this environment, fetch
`https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js` some other way (browser download, another
machine) and place the file at that exact path before continuing — the rest of this task
depends on it existing.

- [ ] **Step 2: Create the CSS**

Create `src/hello_coin/dashboard/static/dashboard.css`:

```css
:root {
  color-scheme: dark;
  --bg: #0f1115;
  --panel-bg: #171a21;
  --border: #2a2f3a;
  --text: #e6e6e6;
  --muted: #9aa4b2;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
}

header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid var(--border);
}

header h1 {
  font-size: 1.1rem;
  margin: 0;
}

#refresh-status {
  margin-left: auto;
  color: var(--muted);
}

main.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  padding: 1rem;
}

.panel {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-bg);
  padding: 1rem;
  overflow-x: auto;
}

.panel.span-2 {
  grid-column: span 2;
}

.panel.error {
  border-color: #ff5c5c;
}

.panel h2 {
  margin-top: 0;
  font-size: 1rem;
}

.coin-panel table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.coin-panel th,
.coin-panel td {
  border-bottom: 1px solid var(--border);
  padding: 0.25rem 0.5rem;
  text-align: left;
  white-space: nowrap;
}

@media (max-width: 800px) {
  main.grid {
    grid-template-columns: 1fr;
  }
  .panel.span-2 {
    grid-column: span 1;
  }
}
```

- [ ] **Step 3: Create the refresh-countdown script**

Create `src/hello_coin/dashboard/static/dashboard.js`:

```javascript
(function () {
  var statusEl = document.getElementById("refresh-status");
  if (!statusEl) {
    return;
  }
  var totalSeconds = parseInt(statusEl.dataset.refreshSeconds, 10) || 60;
  var remaining = totalSeconds;

  function render() {
    statusEl.textContent = "LIVE · Next refresh: " + remaining + "s";
  }

  function tick() {
    remaining = remaining > 0 ? remaining - 1 : totalSeconds;
    render();
  }

  render();
  setInterval(tick, 1000);

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "panels") {
      remaining = totalSeconds;
      render();
    }
  });
})();
```

- [ ] **Step 4: Create the page shell template**

Create `src/hello_coin/dashboard/templates/page.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hello Coin Dashboard</title>
  <link rel="stylesheet" href="/static/dashboard.css">
  <script src="/static/htmx.min.js"></script>
</head>
<body>
  <header>
    <h1>Hello Coin Dashboard</h1>
    <form method="get" action="/">
      <label for="symbol-select">Symbol</label>
      <select id="symbol-select" name="symbol" onchange="this.form.submit()">
        {% for choice in symbols %}
        <option value="{{ choice }}" {% if choice == symbol %}selected{% endif %}>{{ choice }}</option>
        {% endfor %}
      </select>
    </form>
    <span id="refresh-status" data-refresh-seconds="{{ refresh_seconds }}">LIVE &middot; Next refresh: {{ refresh_seconds }}s</span>
  </header>
  <main
    id="panels"
    class="grid"
    hx-get="/panels?symbol={{ symbol }}"
    hx-trigger="every {{ refresh_seconds }}s"
    hx-swap="innerHTML"
  >
    {% include "_panels.html" %}
  </main>
  <script src="/static/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 5: Create the polled panels fragment template**

Create `src/hello_coin/dashboard/templates/_panels.html`:

```html
{% if error %}
<div id="system-status" class="panel span-2 error">
  <h2>System status</h2>
  <p>Refresh error: {{ error }}</p>
</div>
{% else %}
<div id="market-overview" class="panel">
  <h2>{{ snapshot.symbol }} &middot; Market overview</h2>
  <p>Close: {{ format_number(snapshot.technical.get("close_price") if snapshot.technical else None) }}</p>
  <p>Timeframe: {{ settings.technical_timeframe }}</p>
</div>

<div id="technical" class="panel">
  <h2>Technical</h2>
  <p>RSI: {{ format_number(snapshot.technical.get("rsi") if snapshot.technical else None) }}</p>
  <p>MACD histogram: {{ format_number(snapshot.technical.get("macd_histogram") if snapshot.technical else None) }}</p>
  <p>EMA: {{ format_number(snapshot.technical.get("ema") if snapshot.technical else None) }}</p>
</div>

<div id="market-bias" class="panel">
  <h2>Market bias</h2>
  <p>{{ snapshot.bias.label }}</p>
  <p>Score: {{ format_number(snapshot.bias.score) }}</p>
  <p>Whale: {{ format_number(snapshot.bias.whale_score) }} &middot; Technical: {{ format_number(snapshot.bias.technical_score) }}</p>
</div>

<div id="whale-activity" class="panel span-2">
  <h2>Whale activity</h2>
  {% if snapshot.whale_events %}
  <ul>
    {% for event in snapshot.whale_events %}
    <li>
      {{ event.timestamp }} &middot; {{ event.source }} &middot; {{ event.symbol }} &middot;
      {{ event.event_type }} &middot; ${{ format_number(event.get("amount_usd")) }}
      <br>
      &nbsp;&nbsp;{{ format_direction(event.get("side")) }} &middot; Leverage: {{ format_event_leverage(event.get("raw")) }}
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <p>No persisted whale events for this symbol.</p>
  {% endif %}
</div>

{% for table in snapshot.coin_positions %}
<div id="{{ coin_panel_id(table.coin) }}" class="panel coin-panel">
  <h2>{{ table.coin }} &middot; {{ table.status.state }}</h2>
  <table>
    <thead>
      <tr>
        <th>Wallet</th><th>Side</th><th>Size</th><th>Position USD</th><th>Leverage</th>
        <th>Entry</th><th>Liquidation</th><th>uPnL</th><th>Age</th>
      </tr>
    </thead>
    <tbody>
      {% if table.rows %}
      {% for row in table.rows %}
      <tr>
        <td>{{ format_wallet(row.get("wallet_address")) }}</td>
        <td>{{ position_side_label(row.get("side")) }}</td>
        <td>{{ format_number(row.get("amount")) }}</td>
        <td>{{ format_number(row.get("amount_usd")) }}</td>
        <td>{{ format_position_leverage(row.get("raw", {})) }}</td>
        <td>{{ format_number(row.get("raw", {}).get("entryPx")) }}</td>
        <td>{{ format_number(row.get("raw", {}).get("liquidationPx")) }}</td>
        <td>{{ format_number(row.get("raw", {}).get("unrealizedPnl")) }}</td>
        <td>{{ format_age(row.get("timestamp"), snapshot.refreshed_at) }}</td>
      </tr>
      {% endfor %}
      {% else %}
      <tr><td colspan="9">{{ table.status.detail or "No fresh positions." }}</td></tr>
      {% endif %}
    </tbody>
  </table>
</div>
{% endfor %}

<div id="system-status" class="panel span-2">
  <h2>System status</h2>
  {% if snapshot.source_statuses %}
  <ul>
    {% for status in snapshot.source_statuses %}
    <li>{{ status.state }}: {{ status.name }} &middot; {{ status.detail }}</li>
    {% endfor %}
  </ul>
  {% else %}
  <p>NOT CONFIGURED: no ingestion source enabled</p>
  {% endif %}
  <p>Informational only &mdash; no orders are sent.</p>
</div>
{% endif %}
```

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/dashboard/static src/hello_coin/dashboard/templates
git commit -m "feat: add web dashboard templates and static assets"
```

---

### Task 6: FastAPI dashboard app

**Files:**
- Create: `src/hello_coin/dashboard/web.py`
- Test: `tests/dashboard/test_web.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/dashboard/test_web.py`:

```python
from datetime import datetime

from fastapi.testclient import TestClient

from hello_coin.dashboard.models import (
    CoinPositionTable,
    DashboardSnapshot,
    MarketBias,
    SourceStatus,
)
from hello_coin.dashboard.web import create_app
from hello_coin.ingestion.config import Settings


class _DashboardService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        self.calls.append(symbol)
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
        )

    def close(self) -> None:
        self.closed = True


class _ActivityDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        self.calls.append(symbol)
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(
                {
                    "timestamp": "2026-08-29T00:00:00+00:00",
                    "source": "hyperliquid",
                    "symbol": "BTC",
                    "event_type": "fill",
                    "side": "buy",
                    "amount_usd": 100_000.0,
                    "raw": '{"leverage": {"type": "cross", "value": 7}}',
                },
                {
                    "timestamp": "2026-08-29T00:00:01+00:00",
                    "source": "whale_alert",
                    "symbol": "BTC",
                    "event_type": "transfer",
                    "side": None,
                    "amount_usd": 50_000.0,
                    "raw": "{}",
                },
            ),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
        )


class _CoinDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
            coin_positions=(
                CoinPositionTable(
                    "LINK",
                    ({
                        "wallet_address": "0x1234567890abcdef", "side": "buy", "amount": 2.0,
                        "amount_usd": 80_000.0, "timestamp": now.isoformat(),
                        "raw": {"leverage": {"type": "cross", "value": 7}, "entryPx": "10",
                                "liquidationPx": "5", "unrealizedPnl": "100"},
                    },),
                    SourceStatus("hyperdash", "LIVE", now, "current position(s)"),
                ),
                CoinPositionTable("SOL", (), SourceStatus("hyperdash", "STALE", now, "no fresh positions")),
                CoinPositionTable("SUI", (), SourceStatus("hyperdash", "ERROR", now, "request failed")),
                CoinPositionTable("NEAR", (), SourceStatus("hyperdash", "NOT CONFIGURED", None, "token missing")),
            ),
        )


class _FailingDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        raise RuntimeError("db locked")


def _settings(*symbols: str) -> Settings:
    return Settings(exchange_watch_symbols=list(symbols), technical_timeframe="1h", _env_file=None)


def test_index_renders_insufficient_data_for_default_symbol():
    service = _DashboardService()
    app = create_app(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "INSUFFICIENT DATA" in response.text
    assert service.calls == ["BTCUSDT"]


def test_index_selects_requested_symbol_via_query_param():
    service = _DashboardService()
    app = create_app(_settings("BTCUSDT", "ETHUSDT"), adapters=[], service=service, start_workers=False)

    with TestClient(app) as client:
        response = client.get("/?symbol=ETHUSDT")

    assert response.status_code == 200
    assert service.calls == ["ETHUSDT"]


def test_panels_endpoint_returns_fresh_snapshot_fragment():
    service = _DashboardService()
    app = create_app(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert "INSUFFICIENT DATA" in response.text
    assert service.calls == ["BTCUSDT"]


def test_panels_renders_direction_and_available_leverage_for_whale_events():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_ActivityDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert "LONG (BUY)" in response.text
    assert "Leverage: 7x" in response.text
    assert "Leverage: N/A" in response.text


def test_panels_renders_one_position_table_per_coin():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_CoinDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    for coin_id in ("coin-link", "coin-sol", "coin-sui", "coin-near"):
        assert f'id="{coin_id}"' in response.text
    assert "cross · 7x" in response.text
    assert "request failed" in response.text
    assert "NOT CONFIGURED" in response.text


def test_externally_supplied_service_is_not_closed_on_shutdown():
    service = _DashboardService()
    app = create_app(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    with TestClient(app) as client:
        client.get("/")

    assert service.closed is False


def test_panels_shows_refresh_error_without_500():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_FailingDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert "Refresh error" in response.text
    assert "db locked" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dashboard/test_web.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.dashboard.web'`

- [ ] **Step 3: Implement the FastAPI app**

Create `src/hello_coin/dashboard/web.py`:

```python
import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hello_coin.dashboard import formatting
from hello_coin.dashboard.models import DashboardSnapshot
from hello_coin.dashboard.service import DashboardService
from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.notifications import TelegramNotifier
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.storage import TechnicalStorage

logger = logging.getLogger(__name__)

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"
REFRESH_SECONDS = 60

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    format_number=formatting.format_number,
    format_wallet=formatting.format_wallet,
    format_age=formatting.format_age,
    format_direction=formatting.format_direction,
    format_event_leverage=formatting.format_event_leverage,
    format_position_leverage=formatting.format_position_leverage,
    position_side_label=formatting.position_side_label,
    coin_panel_id=formatting.coin_panel_id,
)


def create_app(
    settings: Settings,
    adapters: list[Adapter],
    *,
    service: DashboardService | Any | None = None,
    start_workers: bool = True,
) -> FastAPI:
    owns_service = service is None
    dashboard_service = service or DashboardService(
        WhaleStorage(DEFAULT_WHALE_DB_PATH),
        TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH),
        timeframe=settings.technical_timeframe,
        lookback_hours=settings.decision_whale_lookback_hours,
        hyperdash_watch_coins=settings.hyperdash_watch_coins,
    )
    background_tasks: list[asyncio.Task[None]] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ingestion_storage: WhaleStorage | None = None
        technical_storage: TechnicalStorage | None = None
        if start_workers:
            ingestion_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
            technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
            notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
            background_tasks.append(
                asyncio.create_task(run_ingestion_forever(adapters, ingestion_storage, notifier))
            )
            background_tasks.append(
                asyncio.create_task(
                    run_technical_forever(
                        settings.exchange_watch_symbols,
                        settings.technical_timeframe,
                        technical_storage,
                        poll_interval_seconds=60,
                    )
                )
            )
        try:
            yield
        finally:
            for task in background_tasks:
                task.cancel()
            for task in background_tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if ingestion_storage is not None:
                ingestion_storage.close()
            if technical_storage is not None:
                technical_storage.close()
            if owns_service:
                dashboard_service.close()

    app = FastAPI(title="Hello Coin Dashboard", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def _snapshot_context(symbol: str) -> dict[str, Any]:
        try:
            snapshot: DashboardSnapshot | None = dashboard_service.load_snapshot(
                symbol, adapters, now=datetime.now(tz=UTC)
            )
            error = None
        except Exception as exc:
            logger.exception("dashboard refresh failed")
            snapshot = None
            error = str(exc)
        return {"snapshot": snapshot, "error": error}

    def _context(request: Request, symbol: str | None) -> dict[str, Any]:
        selected = symbol or settings.exchange_watch_symbols[0]
        return {
            "request": request,
            "settings": settings,
            "symbol": selected,
            "symbols": settings.exchange_watch_symbols,
            "refresh_seconds": REFRESH_SECONDS,
            **_snapshot_context(selected),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, symbol: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse("page.html", _context(request, symbol))

    @app.get("/panels", response_class=HTMLResponse)
    async def panels(request: Request, symbol: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse("_panels.html", _context(request, symbol))

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/dashboard/test_web.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/dashboard/web.py tests/dashboard/test_web.py
git commit -m "feat: add FastAPI web dashboard app"
```

---

### Task 7: CLI wiring and Textual removal

**Files:**
- Modify: `src/hello_coin/cli.py:1-30,130-133`
- Delete: `src/hello_coin/dashboard/app.py`
- Delete: `tests/dashboard/test_app.py`
- Modify: `pyproject.toml` (remove `textual`)

- [ ] **Step 1: Point the CLI at the web app**

In `src/hello_coin/cli.py`, change the import:

```python
from hello_coin.dashboard.app import DashboardApp
```

to:

```python
import uvicorn

from hello_coin.dashboard.web import create_app
```

(`import uvicorn` goes with the other top-level imports at the very top of the file, above the
`from anthropic import AsyncAnthropic` line, per the existing import ordering: stdlib first,
then third-party, then local.)

Then change `_run_dashboard()`:

```python
def _run_dashboard() -> None:
    settings = Settings()
    DashboardApp(settings=settings, adapters=build_adapters(settings)).run()
```

to:

```python
def _run_dashboard() -> None:
    settings = Settings()
    app = create_app(settings=settings, adapters=build_adapters(settings))
    uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port)
```

- [ ] **Step 2: Delete the Textual app and its tests**

```bash
git rm src/hello_coin/dashboard/app.py tests/dashboard/test_app.py
```

- [ ] **Step 3: Remove the textual dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    "anthropic>=1.0.0",
    "fastapi>=0.115.0",
    "httpx>=0.28.1",
    "jinja2>=3.1.4",
    "pydantic-settings>=2.15.0",
    "textual>=0.55.0",
    "uvicorn>=0.34.0",
]
```

to:

```toml
dependencies = [
    "anthropic>=1.0.0",
    "fastapi>=0.115.0",
    "httpx>=0.28.1",
    "jinja2>=3.1.4",
    "pydantic-settings>=2.15.0",
    "uvicorn>=0.34.0",
]
```

- [ ] **Step 4: Sync dependencies (uninstalls textual)**

Run: `uv sync`
Expected: `textual` and its now-unused transitive deps are removed from the environment;
`uv.lock` updates.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS, with no references to `textual` remaining anywhere. Confirm with:

Run: `uv run ruff check .`
Expected: no errors (in particular, no unused-import errors from the deleted `DashboardApp`
import).

- [ ] **Step 6: Smoke-test the running server**

Run: `uv run hello-coin dashboard` in the background, then check it serves HTML:

```bash
uv run hello-coin dashboard &
sleep 2
curl -s http://127.0.0.1:8080/ | grep -o "Hello Coin Dashboard"
kill %1
```

Expected: prints `Hello Coin Dashboard`. (If `DASHBOARD_HOST`/`DASHBOARD_PORT` are overridden in
your local `.env`, adjust the URL accordingly.)

- [ ] **Step 7: Commit**

```bash
git add src/hello_coin/cli.py pyproject.toml uv.lock
git commit -m "feat: serve the dashboard over HTTP instead of a terminal UI"
```

---

### Task 8: Docker packaging

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: Write the Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .
RUN uv sync --frozen

EXPOSE 8080

CMD ["uv", "run", "hello-coin", "dashboard"]
```

- [ ] **Step 2: Write docker-compose.yml**

Create `docker-compose.yml`:

```yaml
services:
  dashboard:
    build: .
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

- [ ] **Step 3: Write .dockerignore**

Create `.dockerignore`:

```
.venv
.git
.idea
.pytest_cache
.ruff_cache
.superpowers
__pycache__
**/__pycache__
data
*.pyc
```

- [ ] **Step 4: Build the image**

Run: `docker compose build`
Expected: builds successfully (installs dependencies via `uv sync --frozen`, no `textual` in the
resolved set).

- [ ] **Step 5: Run the container and verify it serves the dashboard**

Run:

```bash
docker compose up -d
sleep 3
curl -s http://localhost:8080/ | grep -o "Hello Coin Dashboard"
docker compose logs dashboard --tail 20
docker compose down
```

Expected: `curl` prints `Hello Coin Dashboard`; logs show no crash/traceback.

- [ ] **Step 6: Confirm data persists across a container restart**

Run:

```bash
docker compose up -d
sleep 3
ls data/whale.db data/technical.db
docker compose down
```

Expected: both files exist on the host under `./data` (created by the container, visible outside
it because of the volume mount).

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat: add Docker packaging for the dashboard service"
```

---

### Task 9: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add Telegram and dashboard-server variables to .env.example**

Append to `.env.example`:

```
# Telegram bot token (create one via @BotFather on Telegram) and the chat ID that should receive
# whale position open/close alerts. Both must be set or no alerts are sent — this is optional,
# not required for the dashboard to run.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Host/port the web dashboard binds to. The default (0.0.0.0:8080) works both for
# `uv run hello-coin dashboard` on the host and for the Docker container (0.0.0.0 so the
# container's published port is reachable from outside it).
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8080
```

- [ ] **Step 2: Replace the README's "Terminal dashboard" section**

In `README.md`, replace:

```markdown
## Terminal dashboard

Run `uv run hello-coin dashboard` to start local whale ingestion, technical collection, and a
terminal dashboard. The display refreshes every 60 seconds and shows a deterministic market bias
from whale (70%) and technical (30%) scores. It never sends orders and does not invoke the
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
```

with:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document Telegram alerts and Docker deployment"
```

---

### Task 10: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: PASS, zero failures.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 3: Confirm no leftover references to the removed Textual dashboard or Windows Toast notifier**

Run: `grep -rn "textual\|WindowsToastNotifier" src tests --include=*.py`
Expected: no matches.

- [ ] **Step 4: Re-run the Docker smoke test end to end**

Run:

```bash
docker compose up -d --build
sleep 3
curl -s http://localhost:8080/ | grep -o "Hello Coin Dashboard"
docker compose down
```

Expected: prints `Hello Coin Dashboard`.
