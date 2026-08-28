import logging
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Footer, Header, Static

from hello_coin.dashboard.models import DashboardSnapshot
from hello_coin.dashboard.service import DashboardService
from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.storage import TechnicalStorage

logger = logging.getLogger(__name__)

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"


class DashboardApp(App[None]):
    TITLE = "Hello Coin Dashboard"
    BINDINGS: ClassVar = [
        ("r", "refresh_dashboard", "Refresh now"),
        ("q", "quit", "Quit"),
    ]
    CSS = """
    Grid {
        grid-size: 3 2;
        grid-gutter: 1;
        padding: 1;
    }

    #market-overview, #technical, #market-bias, #whale-activity, #system-status {
        border: round $primary;
        padding: 1;
    }

    #whale-activity {
        column-span: 2;
    }
    """

    def __init__(
        self,
        settings: Settings,
        adapters: list[Adapter],
        *,
        service: DashboardService | Any | None = None,
        start_workers: bool = True,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._adapters = adapters
        self._start_workers = start_workers
        self._owns_service = service is None
        self._next_refresh_at = datetime.now(tz=UTC)
        self._service = service or DashboardService(
            WhaleStorage(DEFAULT_WHALE_DB_PATH),
            TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH),
            timeframe=settings.technical_timeframe,
            lookback_hours=settings.decision_whale_lookback_hours,
        )
        self.selected_symbol = settings.exchange_watch_symbols[0]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="refresh-status")
        with Grid():
            yield Static(id="market-overview")
            yield Static(id="technical")
            yield Static(id="market-bias")
            yield Static(id="whale-activity")
            yield Static(id="system-status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.set_interval(60, self.refresh_dashboard, name="dashboard-refresh")
        self.set_interval(1, self._update_refresh_status, name="dashboard-countdown")
        if self._start_workers:
            self.run_ingestion_worker()
            self.run_technical_worker()

    def on_unmount(self) -> None:
        self.workers.cancel_all()
        if self._owns_service:
            self._service.close()

    def on_key(self, event: events.Key) -> None:
        if not event.key.isdigit() or event.key == "0":
            return
        symbol_index = int(event.key) - 1
        if symbol_index >= len(self._settings.exchange_watch_symbols):
            return
        self.selected_symbol = self._settings.exchange_watch_symbols[symbol_index]
        self.refresh_dashboard()
        event.stop()

    def action_refresh_dashboard(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        self._next_refresh_at = datetime.now(tz=UTC) + timedelta(seconds=60)
        self._update_refresh_status()
        try:
            snapshot = self._service.load_snapshot(
                self.selected_symbol,
                self._adapters,
                now=datetime.now(tz=UTC),
            )
        except Exception as error:
            logger.exception("dashboard refresh failed")
            self.query_one("#system-status", Static).update(f"Refresh error: {error}")
            return
        self._render_snapshot(snapshot)

    def _update_refresh_status(self) -> None:
        remaining_seconds = max(
            0, round((self._next_refresh_at - datetime.now(tz=UTC)).total_seconds())
        )
        self.query_one("#refresh-status", Static).update(
            f"LIVE · Next refresh: {remaining_seconds}s"
        )

    def _render_snapshot(self, snapshot: DashboardSnapshot) -> None:
        technical = snapshot.technical
        close_price = self._format_number(technical.get("close_price") if technical else None)
        self.query_one("#market-overview", Static).update(
            f"[b]{snapshot.symbol} · Market overview[/b]\nClose: {close_price}\n"
            f"Timeframe: {self._settings.technical_timeframe}"
        )
        self.query_one("#technical", Static).update(
            "[b]Technical[/b]\n"
            f"RSI: {self._format_number(technical.get('rsi') if technical else None)}\n"
            f"MACD histogram: {self._format_number(technical.get('macd_histogram') if technical else None)}\n"
            f"EMA: {self._format_number(technical.get('ema') if technical else None)}"
        )
        bias_score = self._format_number(snapshot.bias.score)
        self.query_one("#market-bias", Static).update(
            f"[b]Market bias[/b]\n{snapshot.bias.label}\nScore: {bias_score}\n"
            f"Whale: {self._format_number(snapshot.bias.whale_score)} · "
            f"Technical: {self._format_number(snapshot.bias.technical_score)}"
        )
        event_lines = ["[b]Whale activity[/b]"]
        for event in snapshot.whale_events:
            value = self._format_number(event.get("amount_usd"))
            event_lines.append(
                f"{event['timestamp']} · {event['source']} · {event['symbol']} · "
                f"{event['event_type']} · ${value}"
            )
        if not snapshot.whale_events:
            event_lines.append("No persisted whale events for this symbol.")
        self.query_one("#whale-activity", Static).update("\n".join(event_lines))
        status_lines = ["[b]System status[/b]"]
        if snapshot.source_statuses:
            status_lines.extend(
                f"{status.state}: {status.name} · {status.detail}"
                for status in snapshot.source_statuses
            )
        else:
            status_lines.append("NOT CONFIGURED: no ingestion source enabled")
        status_lines.append("Informational only — no orders are sent.")
        self.query_one("#system-status", Static).update("\n".join(status_lines))

    @staticmethod
    def _format_number(value: object) -> str:
        if value is None:
            return "unavailable"
        if isinstance(value, int | float):
            return f"{value:,.4f}"
        return str(value)

    @work(exit_on_error=False)
    async def run_ingestion_worker(self) -> None:
        storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
        try:
            await run_ingestion_forever(self._adapters, storage)
        finally:
            storage.close()

    @work(exit_on_error=False)
    async def run_technical_worker(self) -> None:
        storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
        try:
            await run_technical_forever(
                self._settings.exchange_watch_symbols,
                self._settings.technical_timeframe,
                storage,
                poll_interval_seconds=60,
            )
        finally:
            storage.close()
