import argparse
import asyncio
import logging

from anthropic import AsyncAnthropic

from hello_coin.decision.scheduler import run_forever as run_decision_forever
from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"
DEFAULT_DECISION_DB_PATH = "data/decisions.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-coin")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    try:
        await run_ingestion_forever(adapters, storage)
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


async def _test_technical(symbol: str) -> None:
    settings = Settings()
    snapshot = await compute_snapshot(symbol, settings.technical_timeframe)
    print(snapshot)


async def _run_decision() -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    decision_storage = DecisionStorage(DEFAULT_DECISION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            await run_decision_forever(
                symbols=settings.exchange_watch_symbols,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                storage=decision_storage,
            )
    finally:
        whale_storage.close()
        technical_storage.close()
        decision_storage.close()


async def _test_decision(symbol: str) -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            decision = await compute_decision(
                symbol=symbol,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
            )
        print(decision)
    finally:
        whale_storage.close()
        technical_storage.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest" and args.ingest_command == "run":
        asyncio.run(_run_ingest())
    elif args.command == "ingest" and args.ingest_command == "test":
        asyncio.run(_test_adapter(args.source))
    elif args.command == "technical" and args.technical_command == "run":
        asyncio.run(_run_technical())
    elif args.command == "technical" and args.technical_command == "test":
        asyncio.run(_test_technical(args.symbol))
    elif args.command == "decision" and args.decision_command == "run":
        asyncio.run(_run_decision())
    elif args.command == "decision" and args.decision_command == "test":
        asyncio.run(_test_decision(args.symbol))
