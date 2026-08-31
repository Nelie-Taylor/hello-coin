import json
import sqlite3
from datetime import datetime
from pathlib import Path

from hello_coin.technical.models import IndicatorSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS technical_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    close_price REAL NOT NULL,
    rsi REAL,
    macd_line REAL,
    macd_signal REAL,
    macd_histogram REAL,
    bb_upper REAL,
    bb_middle REAL,
    bb_lower REAL,
    ema REAL,
    atr REAL,
    raw TEXT NOT NULL,
    UNIQUE(symbol, timeframe, timestamp)
)
"""


class TechnicalStorage:
    """SQLite-backed storage for technical-indicator snapshots. No business
    logic — just insert (deduped) and basic reads for later consumers."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def insert_snapshot(self, snapshot: IndicatorSnapshot) -> int:
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO technical_snapshots
                (symbol, timeframe, timestamp, close_price, rsi, macd_line, macd_signal,
                 macd_histogram, bb_upper, bb_middle, bb_lower, ema, atr, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.symbol,
                snapshot.timeframe,
                snapshot.timestamp.isoformat(),
                snapshot.close_price,
                snapshot.rsi,
                snapshot.macd_line,
                snapshot.macd_signal,
                snapshot.macd_histogram,
                snapshot.bb_upper,
                snapshot.bb_middle,
                snapshot.bb_lower,
                snapshot.ema,
                snapshot.atr,
                json.dumps(snapshot.raw),
            ),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_snapshots(self, symbol: str | None = None) -> int:
        if symbol is None:
            row = self._conn.execute("SELECT COUNT(*) FROM technical_snapshots").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM technical_snapshots WHERE symbol = ?", (symbol,)
            ).fetchone()
        return int(row[0])

    def latest_snapshot(self, symbol: str, timeframe: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT symbol, timeframe, timestamp, close_price, rsi, macd_line, macd_signal,
                   macd_histogram, bb_upper, bb_middle, bb_lower, ema, atr, raw
            FROM technical_snapshots
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol, timeframe),
        ).fetchone()
        if row is None:
            return None
        columns = (
            "symbol",
            "timeframe",
            "timestamp",
            "close_price",
            "rsi",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "ema",
            "atr",
            "raw",
        )
        return dict(zip(columns, row, strict=True))

    def recent_snapshots(self, symbol: str, timeframe: str, since: datetime) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT symbol, timeframe, timestamp, close_price, rsi, macd_line, macd_signal,
                   macd_histogram, bb_upper, bb_middle, bb_lower, ema, atr, raw
            FROM technical_snapshots
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (symbol, timeframe, since.isoformat()),
        ).fetchall()
        columns = (
            "symbol",
            "timeframe",
            "timestamp",
            "close_price",
            "rsi",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "ema",
            "atr",
            "raw",
        )
        return [dict(zip(columns, row, strict=True)) for row in rows]
