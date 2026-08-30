import argparse
import asyncio
import logging
from pathlib import Path

import uvicorn
from anthropic import AsyncAnthropic

from hello_coin.dashboard.web import create_app
from hello_coin.decision.scheduler import run_forever as run_decision_forever
from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.notifications import TelegramNotifier
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.liquidation.coinglass import is_configured as liquidation_is_configured
from hello_coin.liquidation.scheduler import run_forever as run_liquidation_forever
from hello_coin.liquidation.service import compute_snapshot as compute_liquidation_snapshot
from hello_coin.liquidation.storage import LiquidationStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"
DEFAULT_DECISION_DB_PATH = "data/decisions.db"
DEFAULT_LIQUIDATION_DB_PATH = "data/liquidation.db"
DASHBOARD_LOG_PATH = Path("data/dashboard.log")


def configure_dashboard_logging() -> None:
    DASHBOARD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(DASHBOARD_LOG_PATH, encoding="utf-8")],
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-coin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "run", help="Run whale ingestion and technical indicators continuously"
    )
    subparsers.add_parser("dashboard", help="Run the terminal market dashboard")

    ingest_parser = subparsers.add_parser("ingest", help="Whale data ingestion commands")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)
    ingest_subparsers.add_parser("run", help="Run the ingestion service continuously")
    ingest_test_parser = ingest_subparsers.add_parser(
        "test", help="Fetch once from a single adapter and print the result"
    )
    ingest_test_parser.add_argument("source", help="Adapter name, e.g. hyperliquid")

    technical_parser = subparsers.add_parser("technical", help="Technical indicator commands")
    technical_subparsers = technical_parser.add_subparsers(
        dest="technical_command", required=True
    )
    technical_subparsers.add_parser("run", help="Run the technical-indicators service continuously")
    technical_test_parser = technical_subparsers.add_parser(
        "test", help="Compute one snapshot for a symbol and print the result"
    )
    technical_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    liquidation_parser = subparsers.add_parser("liquidation", help="Liquidation heatmap commands")
    liquidation_subparsers = liquidation_parser.add_subparsers(
        dest="liquidation_command", required=True
    )
    liquidation_subparsers.add_parser(
        "run", help="Run the liquidation-heatmap service continuously"
    )
    liquidation_test_parser = liquidation_subparsers.add_parser(
        "test", help="Fetch one heatmap snapshot for a symbol and print the result"
    )
    liquidation_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    decision_parser = subparsers.add_parser("decision", help="AI decision engine commands")
    decision_subparsers = decision_parser.add_subparsers(dest="decision_command", required=True)
    decision_subparsers.add_parser("run", help="Run the decision engine continuously")
    decision_test_parser = decision_subparsers.add_parser(
        "test", help="Compute one decision for a symbol and print the result"
    )
    decision_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

    return parser


async def _run_ingest() -> None:
    settings = Settings()
    adapters = build_adapters(settings)
    storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    try:
        await run_ingestion_forever(adapters, storage, notifier)
    finally:
        storage.close()


async def _test_adapter(source: str) -> None:
    settings = Settings()
    adapters = {adapter.name: adapter for adapter in build_adapters(settings)}
    adapter = adapters.get(source)
    if adapter is None:
        print(f"Unknown or unconfigured adapter: {source}")
        return
    events = await adapter.fetch()
    for event in events:
        print(event)


async def _run_technical() -> None:
    settings = Settings()
    storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    try:
        await run_technical_forever(
            settings.exchange_watch_symbols, settings.technical_timeframe, storage
        )
    finally:
        storage.close()


async def _run_market_data() -> None:
    await asyncio.gather(_run_ingest(), _run_technical())


def _run_dashboard() -> None:
    settings = Settings()
    app = create_app(settings=settings, adapters=build_adapters(settings))
    uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port)


async def _test_technical(symbol: str) -> None:
    settings = Settings()
    snapshot = await compute_snapshot(symbol, settings.technical_timeframe)
    print(snapshot)


async def _run_liquidation() -> None:
    settings = Settings()
    if not liquidation_is_configured(settings):
        print("COINGLASS_API_KEY is not set — the liquidation service is not configured.")
        return
    storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    try:
        await run_liquidation_forever(
            settings.exchange_watch_symbols,
            settings.coinglass_api_key,
            storage,
            poll_interval_seconds=settings.liquidation_poll_interval_seconds,
        )
    finally:
        storage.close()


async def _test_liquidation(symbol: str) -> None:
    settings = Settings()
    if not liquidation_is_configured(settings):
        print("COINGLASS_API_KEY is not set — the liquidation service is not configured.")
        return
    snapshot = await compute_liquidation_snapshot(symbol, settings.coinglass_api_key)
    print(snapshot)


async def _run_decision() -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    liquidation_storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    decision_storage = DecisionStorage(DEFAULT_DECISION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            await run_decision_forever(
                symbols=settings.exchange_watch_symbols,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                storage=decision_storage,
                liquidation_proximity_pct=settings.liquidation_proximity_pct,
            )
    finally:
        whale_storage.close()
        technical_storage.close()
        liquidation_storage.close()
        decision_storage.close()


async def _test_decision(symbol: str) -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    liquidation_storage = LiquidationStorage(DEFAULT_LIQUIDATION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            decision = await compute_decision(
                symbol=symbol,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                liquidation_storage=liquidation_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                liquidation_proximity_pct=settings.liquidation_proximity_pct,
            )
        print(decision)
    finally:
        whale_storage.close()
        technical_storage.close()
        liquidation_storage.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "dashboard":
        configure_dashboard_logging()
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "run":
        asyncio.run(_run_market_data())
    elif args.command == "dashboard":
        _run_dashboard()
    elif args.command == "ingest" and args.ingest_command == "run":
        asyncio.run(_run_ingest())
    elif args.command == "ingest" and args.ingest_command == "test":
        asyncio.run(_test_adapter(args.source))
    elif args.command == "technical" and args.technical_command == "run":
        asyncio.run(_run_technical())
    elif args.command == "technical" and args.technical_command == "test":
        asyncio.run(_test_technical(args.symbol))
    elif args.command == "liquidation" and args.liquidation_command == "run":
        asyncio.run(_run_liquidation())
    elif args.command == "liquidation" and args.liquidation_command == "test":
        asyncio.run(_test_liquidation(args.symbol))
    elif args.command == "decision" and args.decision_command == "run":
        asyncio.run(_run_decision())
    elif args.command == "decision" and args.decision_command == "test":
        asyncio.run(_test_decision(args.symbol))
