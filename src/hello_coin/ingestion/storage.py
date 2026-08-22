import json
import sqlite3
from pathlib import Path

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric

_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    chain_or_exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    side TEXT,
    amount REAL NOT NULL,
    amount_usd REAL,
    wallet_address TEXT,
    dedup_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(source, dedup_key)
)
"""

_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    dedup_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(source, dedup_key)
)
"""


class WhaleStorage:
    """SQLite-backed storage for normalized whale data. No business logic —
    just insert (deduped) and basic reads for later consumers."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_EVENTS_SCHEMA)
        self._conn.execute(_METRICS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_events(self, events: list[WhaleEvent]) -> int:
        inserted = 0
        for event in events:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO whale_events
                    (source, timestamp, chain_or_exchange, symbol, event_type, side,
                     amount, amount_usd, wallet_address, dedup_key, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    event.timestamp.isoformat(),
                    event.chain_or_exchange,
                    event.symbol,
                    event.event_type,
                    event.side,
                    event.amount,
                    event.amount_usd,
                    event.wallet_address,
                    event.dedup_key,
                    json.dumps(event.raw),
                ),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def insert_metrics(self, metrics: list[WhaleMetric]) -> int:
        inserted = 0
        for metric in metrics:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO whale_metrics
                    (source, timestamp, symbol, metric_name, value, dedup_key, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric.source,
                    metric.timestamp.isoformat(),
                    metric.symbol,
                    metric.metric_name,
                    metric.value,
                    metric.dedup_key,
                    json.dumps(metric.raw),
                ),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def count_events(self, source: str | None = None) -> int:
        if source is None:
            row = self._conn.execute("SELECT COUNT(*) FROM whale_events").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM whale_events WHERE source = ?", (source,)
            ).fetchone()
        return int(row[0])
