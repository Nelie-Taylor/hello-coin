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
            bias=MarketBias(None, None, "INSUFFICIENT DATA"),
            source_statuses=(),
            refreshed_at=now,
        )

    def close(self) -> None:
        self.closed = True


class _CoinDashboardService(_DashboardService):
    def load_snapshot(self, symbol: str, sources: list[object], now: datetime) -> DashboardSnapshot:
        return DashboardSnapshot(
            symbol=symbol,
            technical=None,
            bias=MarketBias(None, None, "INSUFFICIENT DATA"),
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
                        "price": 10.52,
                    },),
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
    assert "10.52" in response.text
