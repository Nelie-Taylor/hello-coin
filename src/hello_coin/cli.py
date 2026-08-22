import argparse
import asyncio
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever
from hello_coin.ingestion.storage import WhaleStorage

DEFAULT_DB_PATH = "data/whale.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-coin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Whale data ingestion commands")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)
    ingest_subparsers.add_parser("run", help="Run the ingestion service continuously")
    test_parser = ingest_subparsers.add_parser(
        "test", help="Fetch once from a single adapter and print the result"
    )
    test_parser.add_argument("source", help="Adapter name, e.g. hyperliquid")

    return parser


async def _run_ingest() -> None:
    settings = Settings()
    adapters = build_adapters(settings)
    storage = WhaleStorage(DEFAULT_DB_PATH)
    try:
        await run_forever(adapters, storage)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest" and args.ingest_command == "run":
        asyncio.run(_run_ingest())
    elif args.command == "ingest" and args.ingest_command == "test":
        asyncio.run(_test_adapter(args.source))
