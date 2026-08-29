import json
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
        grid-size: 3 6;
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

    .coin-position-panel {
        column-span: 1;
        border: round $primary;
        padding: 1;
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
            hyperdash_watch_coins=settings.hyperdash_watch_coins,
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
            for coin in self._settings.hyperdash_watch_coins:
                yield Static(id=self._coin_panel_id(coin), classes="coin-position-panel")
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
            direction = self._format_direction(event.get("side"))
            leverage = self._format_leverage(event.get("raw"))
            event_lines.append(
                f"{event['timestamp']} · {event['source']} · {event['symbol']} · "
                f"{event['event_type']} · ${value}"
            )
            event_lines.append(f"  {direction} \N{MIDDLE DOT} Leverage: {leverage}")
        if not snapshot.whale_events:
            event_lines.append("No persisted whale events for this symbol.")
        self.query_one("#whale-activity", Static).update("\n".join(event_lines))
        self._render_coin_positions(snapshot)
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

    def _render_coin_positions(self, snapshot: DashboardSnapshot) -> None:
        headers = "Wallet | Side | Size | Position USD | Leverage | Entry | Liquidation | uPnL | Age"
        for table in snapshot.coin_positions:
            lines = [f"[b]{table.coin} · {table.status.state}[/b]", headers]
            if not table.rows:
                lines.append(table.status.detail or "No fresh positions.")
            else:
                for row in table.rows:
                    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
                    side = "LONG" if row.get("side") == "buy" else "SHORT" if row.get("side") == "sell" else "N/A"
                    lines.append(" | ".join((
                        self._format_wallet(row.get("wallet_address")), side,
                        self._format_number(row.get("amount")), self._format_number(row.get("amount_usd")),
                        self._format_position_leverage(raw), self._format_number(raw.get("entryPx")),
                        self._format_number(raw.get("liquidationPx")), self._format_number(raw.get("unrealizedPnl")),
                        self._format_age(row.get("timestamp"), snapshot.refreshed_at),
                    )))
            self.query_one(f"#{self._coin_panel_id(table.coin)}", Static).update("\n".join(lines))

    @staticmethod
    def _coin_panel_id(coin: str) -> str:
        return "coin-" + "".join(character.lower() if character.isalnum() else "-" for character in coin)

    @staticmethod
    def _format_wallet(value: object) -> str:
        text = str(value or "N/A")
        return text if len(text) <= 14 else f"{text[:7]}…{text[-5:]}"

    @staticmethod
    def _format_age(value: object, now: datetime) -> str:
        try:
            timestamp = datetime.fromisoformat(str(value))
            return f"{max(0, int((now - timestamp).total_seconds()))}s"
        except (TypeError, ValueError):
            return "N/A"

    @staticmethod
    def _format_position_leverage(raw: dict[str, Any]) -> str:
        leverage = raw.get("leverage")
        if not isinstance(leverage, dict):
            return "N/A"
        value = leverage.get("value")
        if not isinstance(value, int | float):
            return "N/A"
        kind = leverage.get("type")
        return f"{kind} · {value:g}x" if kind else f"{value:g}x"

    @staticmethod
    def _format_number(value: object) -> str:
        if value is None:
            return "unavailable"
        if isinstance(value, int | float):
            return f"{value:,.4f}"
        return str(value)

    @staticmethod
    def _format_direction(side: object) -> str:
        if side == "buy":
            return "LONG (BUY)"
        if side == "sell":
            return "SHORT (SELL)"
        return "N/A"

    @staticmethod
    def _format_leverage(raw: object) -> str:
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
