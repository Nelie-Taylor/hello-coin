import json
import sqlite3
from datetime import datetime
from pathlib import Path

from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS liquidation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    current_price REAL NOT NULL,
    buckets TEXT NOT NULL,
    UNIQUE(symbol, timestamp)
)
"""


class LiquidationStorage:
    """SQLite-backed storage for liquidation heatmap snapshots. No business
    logic — just insert (deduped) and basic reads for later consumers.
    `latest_snapshot` reconstructs a full `LiquidationSnapshot` (not a flat
    dict) since `liquidation/score.py`'s functions operate on that shape."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_snapshot(self, snapshot: LiquidationSnapshot) -> int:
        buckets_json = json.dumps([[b.price, b.notional_usd] for b in snapshot.buckets])
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO liquidation_snapshots
                (symbol, timestamp, current_price, buckets)
            VALUES (?, ?, ?, ?)
            """,
            (
                snapshot.symbol,
                snapshot.timestamp.isoformat(),
                snapshot.current_price,
                buckets_json,
            ),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_snapshots(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute("SELECT COUNT(*) FROM liquidation_snapshots").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM liquidation_snapshots WHERE symbol = ?", (symbol,)
            ).fetchone()
        return int(row[0])

    def latest_snapshot(self, symbol: str) -> LiquidationSnapshot | None:
        row = self._conn.execute(
            """
            SELECT symbol, timestamp, current_price, buckets
            FROM liquidation_snapshots
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        symbol_value, timestamp, current_price, buckets_json = row
        buckets = [
            LiquidationBucket(price=price, notional_usd=notional_usd)
            for price, notional_usd in json.loads(buckets_json)
        ]
        return LiquidationSnapshot(
            symbol=symbol_value,
            timestamp=datetime.fromisoformat(timestamp),
            current_price=current_price,
            buckets=buckets,
        )
