import json
import sqlite3
from pathlib import Path

from hello_coin.decision.models import Decision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    whale_score REAL,
    technical_score REAL,
    weighted_score REAL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(symbol, timestamp)
)
"""


class DecisionStorage:
    """SQLite-backed storage for AI trade decisions. No business logic —
    just insert (deduped) and basic reads for later consumers."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_decision(self, decision: Decision) -> int:
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO decisions
                (symbol, timestamp, whale_score, technical_score, weighted_score, action,
                 confidence, reasoning, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.symbol,
                decision.timestamp.isoformat(),
                decision.whale_score,
                decision.technical_score,
                decision.weighted_score,
                decision.action,
                decision.confidence,
                decision.reasoning,
                json.dumps(decision.raw),
            ),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_decisions(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE symbol = ?", (symbol,)
            ).fetchone()
        return int(row[0])
