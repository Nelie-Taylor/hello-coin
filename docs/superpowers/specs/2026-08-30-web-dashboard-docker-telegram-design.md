# Web dashboard, Docker deployment, Telegram alerts — design

Date: 2026-08-30

## Problem

The current dashboard (`hello-coin dashboard`) is a Textual TUI: it only renders in a terminal
attached to the process, and its whale-position-change alerts (`WindowsToastNotifier`) shell out
to PowerShell and only work on Windows. Neither survives moving the service into Docker: a
container has no attached terminal to view a TUI in, and Linux containers have no PowerShell/
Windows Toast API. This design replaces both so the service can run in Docker with the dashboard
viewable from a browser and whale alerts delivered via Telegram.

Scope is presentation-layer only. `DashboardService`, `DashboardSnapshot`, `MarketBias`, and the
whale/technical data pipelines are unchanged — only how the snapshot is displayed and how position
changes are announced.

## 1. Web dashboard (FastAPI, replaces Textual)

`src/hello_coin/dashboard/app.py` (Textual `DashboardApp`) is deleted and replaced by a FastAPI
app in the same package. `models.py` and `service.py` are untouched — `DashboardService.load_snapshot()`
remains the single source of truth for what gets rendered.

- `GET /` — renders the full page (Jinja2 template): header, refresh countdown, a 2-column grid
  matching the current panel set (market overview, technical, market bias, whale activity
  full-width, one panel per configured Hyperdash coin, system status full-width). Accepts an
  optional `?symbol=` query param (defaults to the first configured `exchange_watch_symbols`
  entry) to pick which symbol's overview/technical/bias panels are shown; a `<select>` dropdown
  in the page lets the user switch symbols (replaces the Textual `1`-`9` keybindings).
- `GET /panels?symbol=...` — returns just the inner panel HTML fragments for the given symbol.
  Polled by HTMX (`hx-get="/panels" hx-trigger="every 60s"`) to refresh data without a full page
  reload. This is the same 60-second cadence the Textual dashboard used.
- Whale ingestion and technical-indicator background loops start as `asyncio` tasks in the FastAPI
  lifespan handler (replacing Textual's `@work` workers) and are cancelled on shutdown, mirroring
  `DashboardApp.on_mount`/`on_unmount` today.
- Static assets: one `static/dashboard.css` (dark theme, grid layout equivalent to the current
  Textual CSS) and a small inline/`static/dashboard.js` script that ticks the refresh countdown
  every second between HTMX polls. No JS framework, no build step.
- Refresh-failure handling: if `load_snapshot()` raises, `/panels` renders a system-status error
  fragment (mirrors today's `except Exception` branch in `refresh_dashboard`) instead of a 500, so
  a transient data error doesn't blank the page.

### CLI wiring

`hello-coin dashboard` starts the web server instead of `DashboardApp().run()`:

```python
def _run_dashboard() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(settings=settings, adapters=build_adapters(settings)),
        host=settings.dashboard_host,
        port=settings.dashboard_port,
    )
```

New `Settings` fields: `dashboard_host: str = "0.0.0.0"`, `dashboard_port: int = 8080`.

### Dependencies

Add `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (form/query parsing) to `pyproject.toml`.
Remove `textual`.

## 2. Telegram notifier (replaces Windows Toast)

`src/hello_coin/ingestion/notifications.py`:

- Delete `WindowsToastNotifier`, `_toast_script`, and the now-unused `base64`/`platform`/
  `subprocess` imports.
- Add `TelegramNotifier`, implementing the existing `NotificationSink` protocol:

```python
class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None,
                 client: httpx.AsyncClient | None = None) -> None: ...

    async def notify(self, change: PositionChange) -> None:
        if not self._bot_token or not self._chat_id:
            return
        title, body = format_position_notification(change)
        try:
            await self._client.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": f"{title}\n{body}"},
                timeout=10,
            )
        except httpx.HTTPError:
            logger.exception("failed to send Telegram notification")
```

- `notify()` becomes `async` (it wasn't before) since it now makes a network call; the
  `NotificationSink` protocol and its one caller in `ingestion/scheduler.py` are updated to
  `await` it. `format_position_notification()` is reused unchanged — message content doesn't
  change, only the delivery channel.
- Missing `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` → silent no-op (same "optional, never
  crashes the service" pattern every other adapter/credential in this codebase follows), not an
  error at startup.
- New `Settings` fields: `telegram_bot_token: str | None = None`, `telegram_chat_id: str | None =
  None`. Documented in `.env.example` next to the other optional credentials.
- `cli.py`'s `_run_ingest()` and the dashboard's ingestion worker both construct
  `TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)` instead of
  `WindowsToastNotifier()`.

## 3. Docker

- **`Dockerfile`** (repo root): `python:3.12-slim` base, install `uv`, `uv sync --frozen
  --no-dev`, copy source, `CMD ["uv", "run", "hello-coin", "dashboard"]`.
- **`docker-compose.yml`** (repo root): single `dashboard` service —
  - `build: .`
  - `env_file: .env`
  - `ports: ["8080:8080"]`
  - `volumes: ["./data:/app/data"]` (persists `whale.db`, `technical.db`, `dashboard.log` across
    container restarts/rebuilds)
  - `restart: unless-stopped`
- `.dockerignore`: `.venv`, `.git`, `data/`, `__pycache__`, `.pytest_cache`, `.ruff_cache`.
- README gets a new "Run with Docker" section: `docker compose up -d`, then open
  `http://localhost:8080`.

Decision/liquidation schedulers are out of scope for the container — they keep running via `uv
run hello-coin decision run` / `liquidation run` from the host (or wherever they run today) if
configured. Only the dashboard's own ingestion + technical loops move into the container, matching
what `hello-coin dashboard` already runs today.

## 4. Testing

- `tests/dashboard/test_app.py` (Textual `App.run_test()`-based) is replaced by
  `tests/dashboard/test_web.py`, using FastAPI's `TestClient` (`httpx.ASGITransport`) against
  `GET /` and `GET /panels`, asserting the rendered HTML contains the expected snapshot data
  (symbol, bias label, whale event lines, coin position rows) — same assertions as today's test,
  against HTML instead of Textual widget content.
- `tests/dashboard/test_models.py` and `test_service.py` are unchanged.
- `tests/ingestion/test_notifications.py`: replace the `WindowsToastNotifier` tests with
  `TelegramNotifier` tests — asserts the POST body/URL against a mocked `httpx.AsyncClient`, and
  that `notify()` is a no-op when `bot_token`/`chat_id` is `None`, and that an `httpx.HTTPError`
  is caught and logged rather than raised.

## Out of scope

- Decision engine / liquidation heatmap are not containerized in this change.
- No authentication on the web dashboard (matches today's trust model: local/private network
  access only — same as the terminal dashboard requiring shell access to the host).
- No HTTPS/TLS termination — assumed to sit behind a reverse proxy or be accessed on a trusted
  network if exposed beyond localhost.
