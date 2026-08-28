import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hello_coin import cli
from hello_coin.cli import build_parser


def test_run_parses():
    parser = build_parser()

    args = parser.parse_args(["run"])

    assert args.command == "run"


@pytest.mark.asyncio
async def test_run_market_data_starts_ingestion_and_technical_together(monkeypatch):
    ingestion_started = asyncio.Event()
    technical_started = asyncio.Event()

    async def run_ingestion():
        ingestion_started.set()
        await technical_started.wait()

    async def run_technical():
        technical_started.set()
        await ingestion_started.wait()

    monkeypatch.setattr(cli, "_run_ingest", run_ingestion)
    monkeypatch.setattr(cli, "_run_technical", run_technical)

    await asyncio.wait_for(cli._run_market_data(), timeout=0.1)


def test_dashboard_parses():
    args = build_parser().parse_args(["dashboard"])

    assert args.command == "dashboard"


def test_main_runs_dashboard_without_creating_ai_client(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hello-coin", "dashboard"])
    settings = SimpleNamespace(exchange_watch_symbols=["BTCUSDT"])
    app = MagicMock()
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "build_adapters", lambda configured: [])
    monkeypatch.setattr(cli, "DashboardApp", lambda settings, adapters: app)

    def fail_if_created(*args, **kwargs):
        raise AssertionError("dashboard must not create an AI client")

    monkeypatch.setattr(cli, "AsyncAnthropic", fail_if_created)

    cli.main()

    app.run.assert_called_once_with()


def test_ingest_run_parses():
    parser = build_parser()

    args = parser.parse_args(["ingest", "run"])

    assert args.command == "ingest"
    assert args.ingest_command == "run"


def test_ingest_test_parses_source():
    parser = build_parser()

    args = parser.parse_args(["ingest", "test", "hyperliquid"])

    assert args.command == "ingest"
    assert args.ingest_command == "test"
    assert args.source == "hyperliquid"


def test_technical_run_parses():
    parser = build_parser()

    args = parser.parse_args(["technical", "run"])

    assert args.command == "technical"
    assert args.technical_command == "run"


def test_technical_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["technical", "test", "BTCUSDT"])

    assert args.command == "technical"
    assert args.technical_command == "test"
    assert args.symbol == "BTCUSDT"


def test_liquidation_run_parses():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "run"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "run"


def test_liquidation_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "test", "BTCUSDT"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "test"
    assert args.symbol == "BTCUSDT"


def test_decision_run_parses():
    parser = build_parser()

    args = parser.parse_args(["decision", "run"])

    assert args.command == "decision"
    assert args.decision_command == "run"


def test_decision_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["decision", "test", "BTCUSDT"])

    assert args.command == "decision"
    assert args.decision_command == "test"
    assert args.symbol == "BTCUSDT"
