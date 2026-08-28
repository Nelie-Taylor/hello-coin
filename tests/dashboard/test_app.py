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


@pytest.mark.asyncio
async def test_dashboard_renders_direction_and_available_leverage_for_whale_events():
    app = DashboardApp(
        _settings("BTCUSDT"),
        adapters=[],
        service=_ActivityDashboardService(),
        start_workers=False,
    )

    async with app.run_test():
        activity = app.query_one("#whale-activity").content

    assert "LONG (BUY)" in activity
    assert "Leverage: 7x" in activity
    assert "Leverage: N/A" in activity
