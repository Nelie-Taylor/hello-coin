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
        return templates.TemplateResponse(request, "page.html", _context(request, symbol))

    @app.get("/panels", response_class=HTMLResponse)
    async def panels(request: Request, symbol: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(request, "_panels.html", _context(request, symbol))

    return app
