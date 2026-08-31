from datetime import datetime, timedelta

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


class _RecentActivityDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        self.calls.append(symbol)
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(
                {
                    "timestamp": (now - timedelta(minutes=5)).isoformat(),
                    "source": "hyperliquid",
                    "symbol": "BTC",
                    "event_type": "fill",
                    "side": "buy",
                    "amount_usd": 100_000.0,
                    "raw": '{"leverage": {"type": "cross", "value": 7}}',
                },
                {
                    "timestamp": (now - timedelta(hours=2)).isoformat(),
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
                    skew_history=({
                        "coin": "LINK", "timestamp": now.isoformat(), "long_usd": 800_000.0,
                        "short_usd": 200_000.0, "long_pct": 0.8, "short_pct": 0.2,
                    },),
                ),
                CoinPositionTable("SOL", (), SourceStatus("hyperdash", "STALE", now, "no fresh positions")),
                CoinPositionTable("SUI", (), SourceStatus("hyperdash", "ERROR", now, "request failed")),
                CoinPositionTable("NEAR", (), SourceStatus("hyperdash", "NOT CONFIGURED", None, "token missing")),
            ),
        )


class _PriceHistoryDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        self.calls.append(symbol)
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            whale_events=(),
            bias=MarketBias(None, None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
            price_history=({
                "symbol": symbol, "timeframe": "1h", "timestamp": now.isoformat(),
                "close_price": 79249.1,
            },),
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


def test_panels_splits_whale_activity_into_all_and_recent_columns():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_RecentActivityDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert "All activity" in response.text
    assert "Recent (last 15m)" in response.text
    # the 5-minute-old event shows in both columns; the 2-hour-old event only in "All activity"
    assert response.text.count("hyperliquid") == 2
    assert response.text.count("whale_alert") == 1


def test_panels_shows_empty_state_when_no_recent_whale_activity():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_ActivityDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert "No whale orders in the last 15 minutes." in response.text


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


def test_panels_renders_price_chart_canvas_with_history_data():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_PriceHistoryDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert 'id="price-chart"' in response.text
    assert 'class="price-chart"' in response.text
    assert "79249.1" in response.text


def test_panels_renders_skew_chart_canvas_with_history_data():
    app = create_app(
        _settings("BTCUSDT"), adapters=[], service=_CoinDashboardService(), start_workers=False
    )

    with TestClient(app) as client:
        response = client.get("/panels?symbol=BTCUSDT")

    assert response.status_code == 200
    assert 'id="coin-link-skew-chart"' in response.text
    assert 'class="skew-chart"' in response.text
    assert "0.8" in response.text
