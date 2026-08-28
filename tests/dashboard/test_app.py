from datetime import datetime

import pytest

from hello_coin.dashboard.app import DashboardApp
from hello_coin.dashboard.models import DashboardSnapshot, MarketBias
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


def _settings(*symbols: str) -> Settings:
    return Settings(exchange_watch_symbols=list(symbols), technical_timeframe="1h")


@pytest.mark.asyncio
async def test_dashboard_selects_second_symbol_with_two_key():
    service = _DashboardService()
    app = DashboardApp(
        _settings("BTCUSDT", "ETHUSDT"), adapters=[], service=service, start_workers=False
    )

    async with app.run_test() as pilot:
        await pilot.press("2")

    assert app.selected_symbol == "ETHUSDT"
    assert service.calls[-1] == "ETHUSDT"


@pytest.mark.asyncio
async def test_dashboard_r_refreshes_current_snapshot():
    service = _DashboardService()
    app = DashboardApp(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    async with app.run_test() as pilot:
        await pilot.press("r")

    assert service.calls == ["BTCUSDT", "BTCUSDT"]


@pytest.mark.asyncio
async def test_dashboard_renders_insufficient_data_without_starting_workers():
    service = _DashboardService()
    app = DashboardApp(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    async with app.run_test():
        assert "INSUFFICIENT DATA" in app.query_one("#market-bias").content

    assert service.closed is False


@pytest.mark.asyncio
async def test_dashboard_displays_countdown_to_next_refresh():
    service = _DashboardService()
    app = DashboardApp(_settings("BTCUSDT"), adapters=[], service=service, start_workers=False)

    async with app.run_test():
        assert "Next refresh:" in app.query_one("#refresh-status").content
