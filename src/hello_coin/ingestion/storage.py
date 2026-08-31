import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric
from hello_coin.ingestion.position_skew import SkewSnapshot

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

_SKEW_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS coin_skew_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    long_usd REAL NOT NULL,
    short_usd REAL NOT NULL,
    long_pct REAL NOT NULL,
    short_pct REAL NOT NULL,
    UNIQUE(coin, timestamp)
)
"""

# Every read below filters with `COLLATE NOCASE`, so the index must be built with the same
# collation — an index on the plain column can't be used by a NOCASE-collated comparison, which
# silently falls back to a full table scan.
_EVENTS_SYMBOL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_whale_events_symbol_timestamp "
    "ON whale_events(symbol COLLATE NOCASE, timestamp)"
)
_METRICS_SYMBOL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_whale_metrics_symbol_timestamp "
    "ON whale_metrics(symbol COLLATE NOCASE, timestamp)"
)
_SKEW_SNAPSHOTS_COIN_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_coin_skew_snapshots_coin_timestamp "
    "ON coin_skew_snapshots(coin COLLATE NOCASE, timestamp)"
)

_SKEW_SNAPSHOT_COLUMNS = ("coin", "timestamp", "long_usd", "short_usd", "long_pct", "short_pct")

_EVENT_COLUMNS = (
    "source",
    "timestamp",
    "chain_or_exchange",
    "symbol",
    "event_type",
    "side",
    "amount",
    "amount_usd",
    "wallet_address",
    "dedup_key",
    "raw",
)


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
        self._conn.execute(_SKEW_SNAPSHOTS_SCHEMA)
        self._conn.execute(_EVENTS_SYMBOL_INDEX)
        self._conn.execute(_METRICS_SYMBOL_INDEX)
        self._conn.execute(_SKEW_SNAPSHOTS_COIN_INDEX)
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

    def recent_events(self, symbol: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT source, timestamp, chain_or_exchange, symbol, event_type, side, amount,
                   amount_usd, wallet_address, dedup_key, raw
            FROM whale_events
            WHERE symbol = ? COLLATE NOCASE AND timestamp >= ?
            """,
            (symbol, since.isoformat()),
        ).fetchall()
        return [dict(zip(_EVENT_COLUMNS, row, strict=True)) for row in rows]

    def latest_events(self, symbol: str | Sequence[str], limit: int = 10) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        symbols = [symbol] if isinstance(symbol, str) else list(symbol)
        placeholders = ", ".join("UPPER(?)" for _ in symbols)
        rows = self._conn.execute(
            f"""
            SELECT source, timestamp, chain_or_exchange, symbol, event_type, side, amount,
                   amount_usd, wallet_address, dedup_key, raw
            FROM whale_events
            WHERE UPPER(symbol) IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*symbols, limit),
        ).fetchall()
        return [dict(zip(_EVENT_COLUMNS, row, strict=True)) for row in rows]

    def recent_metrics(self, symbol: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT source, timestamp, symbol, metric_name, value, dedup_key, raw
            FROM whale_metrics
            WHERE symbol = ? COLLATE NOCASE AND timestamp >= ?
            """,
            (symbol, since.isoformat()),
        ).fetchall()
        columns = ("source", "timestamp", "symbol", "metric_name", "value", "dedup_key", "raw")
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def insert_skew_snapshots(self, snapshots: list[SkewSnapshot]) -> int:
        inserted = 0
        for snapshot in snapshots:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO coin_skew_snapshots
                    (coin, timestamp, long_usd, short_usd, long_pct, short_pct)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.coin,
                    snapshot.timestamp.isoformat(),
                    snapshot.long_usd,
                    snapshot.short_usd,
                    snapshot.long_pct,
                    snapshot.short_pct,
                ),
            )
            inserted += cursor.rowcount
        if snapshots:
            # Deriving the cutoff from the batch's own latest timestamp (rather than
            # datetime.now()) keeps this deterministic and testable, and pruning naturally
            # happens on every adapter poll cycle that has fresh data.
            cutoff = max(snapshot.timestamp for snapshot in snapshots) - timedelta(days=30)
            self._conn.execute(
                "DELETE FROM coin_skew_snapshots WHERE timestamp < ?", (cutoff.isoformat(),)
            )
        self._conn.commit()
        return inserted

    def recent_skew_history(self, coin: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT coin, timestamp, long_usd, short_usd, long_pct, short_pct
            FROM coin_skew_snapshots
            WHERE coin = ? COLLATE NOCASE AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (coin, since.isoformat()),
        ).fetchall()
        return [dict(zip(_SKEW_SNAPSHOT_COLUMNS, row, strict=True)) for row in rows]
