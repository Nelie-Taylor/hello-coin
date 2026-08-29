import asyncio
import logging
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


@pytest.mark.asyncio
async def test_run_ingest_passes_windows_notifier_to_ingestion_runner(monkeypatch):
    settings = SimpleNamespace()
    storage = MagicMock()
    notifier = MagicMock()
    captured: dict[str, object] = {}

    async def run_ingestion(adapters, received_storage, received_notifier):
        captured["adapters"] = adapters
        captured["storage"] = received_storage
        captured["notifier"] = received_notifier

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "build_adapters", lambda received_settings: ["adapter"])
    monkeypatch.setattr(cli, "WhaleStorage", lambda path: storage)
    monkeypatch.setattr(cli, "WindowsToastNotifier", lambda: notifier)
    monkeypatch.setattr(cli, "run_ingestion_forever", run_ingestion)

    await cli._run_ingest()

    assert captured == {"adapters": ["adapter"], "storage": storage, "notifier": notifier}
    storage.close.assert_called_once_with()


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


def test_dashboard_logging_writes_to_file_without_terminal_handler(tmp_path, monkeypatch):
    root_logger = logging.getLogger()
    previous_handlers = root_logger.handlers[:]
    previous_level = root_logger.level
    log_path = tmp_path / "dashboard.log"
    monkeypatch.setattr(cli, "DASHBOARD_LOG_PATH", log_path)

    try:
        cli.configure_dashboard_logging()
        logging.getLogger("hello_coin.dashboard_test").warning("dashboard log record")
        for handler in root_logger.handlers:
            handler.flush()

        assert "dashboard log record" in log_path.read_text(encoding="utf-8")
        assert all(isinstance(handler, logging.FileHandler) for handler in root_logger.handlers)
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.handlers.extend(previous_handlers)
        root_logger.setLevel(previous_level)


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
