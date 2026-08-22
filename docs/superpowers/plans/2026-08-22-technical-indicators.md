# Technical Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the technical-indicators module (`src/hello_coin/technical/`) so
`uv run hello-coin technical run` polls Binance's public klines endpoint for every symbol in
`exchange_watch_symbols`, computes RSI/MACD/Bollinger Bands/EMA/ATR locally, and stores one
`IndicatorSnapshot` per symbol per poll in `data/technical.db` — the 30%-weighted signal source
alongside the existing whale-ingestion layer.

**Architecture:** Per
`docs/superpowers/specs/2026-08-22-technical-indicators-design.md`: a package sibling to
`ingestion/`, not nested inside it. `indicators.py` holds pure functions (no HTTP, no models) so
every indicator is tested against hand-verified reference values with zero mocking. `klines.py`
is the only network-facing module. `service.py` wires fetch + compute together. There is no
`Adapter`-style registry — one data source (Binance klines), so `scheduler.py` iterates directly
over `exchange_watch_symbols`.

**Reference values used in tests:** every indicator's expected value below was computed by a
standalone reference script (Wilder's smoothing for RSI/ATR, standard EMA seeded with SMA,
population standard deviation for Bollinger Bands) and hand-verified by tracing the arithmetic —
see each task's "Reference calculation" note. These are pure-math golden values, not fetched
from any third party, so there's nothing to "verify live" here the way the whale-data API shapes
needed to be.

**Tech Stack:** Same as `ingestion/` — `httpx` (async HTTP), stdlib `sqlite3`, stdlib `asyncio`,
`pytest` + `pytest-asyncio` + `respx`. No pandas/numpy — plain Python floats and lists.

---

### Task 1: Package scaffolding and data models

**Files:**
- Create: `src/hello_coin/technical/__init__.py`
- Create: `src/hello_coin/technical/models.py`
- Test: `tests/technical/test_models.py`
- Create: `tests/technical/` (directory)

- [ ] **Step 1: Create the package**

Create `src/hello_coin/technical/__init__.py` (empty file).

Create the `tests/technical/` directory.

- [ ] **Step 2: Write the failing test**

Create `tests/technical/test_models.py`:

```python
from datetime import datetime, timezone

from hello_coin.technical.models import Candle, IndicatorSnapshot


def test_candle_holds_fields():
    candle = Candle(
        open_time=datetime(2026, 8, 22, tzinfo=timezone.utc),
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=12.5,
    )

    assert candle.close == 104.0
    assert candle.volume == 12.5


def test_indicator_snapshot_allows_none_fields_before_enough_history():
    snapshot = IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        close_price=104.0,
        rsi=None,
        macd_line=None,
        macd_signal=None,
        macd_histogram=None,
        bb_upper=None,
        bb_middle=None,
        bb_lower=None,
        ema=None,
        atr=None,
        raw={"candle_count": 5},
    )

    assert snapshot.rsi is None
    assert snapshot.raw == {"candle_count": 5}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.models'`

- [ ] **Step 4: Write the implementation**

Create `src/hello_coin/technical/models.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IndicatorSnapshot:
    """A point-in-time snapshot of every computed indicator for one symbol.

    Each indicator field is `float | None` — `None` means there wasn't yet
    enough candle history to compute it, not a fabricated value.
    """

    symbol: str
    timeframe: str
    timestamp: datetime
    close_price: float
    rsi: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    ema: float | None
    atr: float | None
    raw: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_models.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/technical/__init__.py src/hello_coin/technical/models.py tests/technical/test_models.py
git commit -m "Add technical-indicators package scaffolding and data models"
```

---

### Task 2: Indicator functions (pure math, hand-verified reference values)

**Files:**
- Create: `src/hello_coin/technical/indicators.py`
- Test: `tests/technical/test_indicators.py`

Every function returns `None` (or an all-`None` tuple) when there isn't enough history, rather
than raising or fabricating a number — callers decide what to do with incomplete data.

- [ ] **Step 1: Write the failing tests**

Create `tests/technical/test_indicators.py`:

```python
import pytest

from hello_coin.technical.indicators import atr, bollinger_bands, ema, macd, rsi


def test_ema_matches_reference_value():
    # Reference calculation: seed = SMA(1,2,3) = 2.0; then EMA(4) = (4-2)*0.5+2 = 3.0;
    # EMA(5) = (5-3)*0.5+3 = 4.0. k = 2/(period+1) = 0.5 for period=3.
    result = ema([1, 2, 3, 4, 5], period=3)
    assert result == pytest.approx(4.0)


def test_ema_returns_none_with_insufficient_data():
    assert ema([1, 2], period=3) is None


def test_rsi_matches_reference_value():
    # Reference calculation (Wilder's smoothing, period=3):
    # diffs from [10,12,11,13,12,14] = [+2,-1,+2,-1,+2]
    # seed avg_gain = (2+0+2)/3 = 4/3, seed avg_loss = (0+1+0)/3 = 1/3
    # step (gain=0,loss=1): avg_gain=(4/3*2+0)/3=8/9, avg_loss=(1/3*2+1)/3=5/9
    # step (gain=2,loss=0): avg_gain=(8/9*2+2)/3=34/27, avg_loss=(5/9*2+0)/3=10/27
    # RS = 34/10 = 3.4; RSI = 100 - 100/(1+3.4) = 850/11 = 77.27272727272727
    result = rsi([10, 12, 11, 13, 12, 14], period=3)
    assert result == pytest.approx(850 / 11)


def test_rsi_returns_none_with_insufficient_data():
    assert rsi([10, 12], period=3) is None


def test_rsi_is_100_when_no_losses():
    result = rsi([10, 11, 12, 13], period=3)
    assert result == pytest.approx(100.0)


def test_macd_matches_reference_value():
    # Reference calculation (fast=3, slow=6, signal=2) on a pure linear series
    # [1..14]: the fast/slow EMA gap converges to a constant (1.5) once both EMAs
    # are past their warm-up window, and the signal EMA of a constant series equals
    # that same constant — so histogram converges to 0.0. Computed via a standalone
    # reference script implementing the same seeded-EMA algorithm; see the plan.
    closes = list(range(1, 15))
    macd_line, signal_line, histogram = macd(closes, fast=3, slow=6, signal=2)
    assert macd_line == pytest.approx(1.5)
    assert signal_line == pytest.approx(1.5)
    assert histogram == pytest.approx(0.0, abs=1e-9)


def test_macd_returns_none_triple_with_insufficient_data():
    macd_line, signal_line, histogram = macd([1, 2, 3], fast=3, slow=6, signal=2)
    assert macd_line is None
    assert signal_line is None
    assert histogram is None


def test_bollinger_bands_matches_reference_value():
    # Reference calculation (period=5, num_std=2) on window [15,16,17,18,19]:
    # mean=17.0; population variance = ((-2)^2+(-1)^2+0+1^2+2^2)/5 = 10/5 = 2.0
    # std = sqrt(2) = 1.4142135623730951
    # upper = 17 + 2*std = 19.82842712474619; lower = 17 - 2*std = 14.17157287525381
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    upper, middle, lower = bollinger_bands(closes, period=5, num_std=2.0)
    assert upper == pytest.approx(19.82842712474619)
    assert middle == pytest.approx(17.0)
    assert lower == pytest.approx(14.17157287525381)


def test_bollinger_bands_returns_none_triple_with_insufficient_data():
    upper, middle, lower = bollinger_bands([1, 2], period=5, num_std=2.0)
    assert upper is None
    assert middle is None
    assert lower is None


def test_atr_matches_reference_value():
    # Reference calculation (Wilder's smoothing, period=3):
    # True ranges from highs/lows/closes below: [3, 2, 3, 3, 3, 4]
    # seed avg_tr = (3+2+3)/3 = 8/3
    # step tr=3: avg_tr=(8/3*2+3)/3=25/9=2.777...
    # step tr=3: avg_tr=(25/9*2+3)/3=77/27=2.851851...
    # step tr=4: avg_tr=(77/27*2+4)/3=262/81=3.2345679012345676
    highs = [10, 12, 11, 13, 15, 14, 16]
    lows = [8, 9, 9, 10, 12, 11, 13]
    closes = [9, 11, 10, 12, 14, 12, 15]
    result = atr(highs, lows, closes, period=3)
    assert result == pytest.approx(3.2345679012345676)


def test_atr_returns_none_with_insufficient_data():
    assert atr([10, 11], [9, 10], [9, 10], period=3) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.indicators'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/technical/indicators.py`:

```python
def _ema_series(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    series: list[float | None] = [None] * (period - 1) + [seed]
    prev = seed
    for value in values[period:]:
        prev = (value - prev) * k + prev
        series.append(prev)
    return series


def ema(values: list[float], period: int) -> float | None:
    series = _ema_series(values, period)
    return series[-1] if series else None


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float | None, float | None, float | None]:
    fast_series = _ema_series(closes, fast)
    slow_series = _ema_series(closes, slow)
    macd_line_series = [
        f - s for f, s in zip(fast_series, slow_series) if f is not None and s is not None
    ]
    if len(macd_line_series) < signal:
        return None, None, None
    signal_series = _ema_series(macd_line_series, signal)
    macd_line = macd_line_series[-1]
    signal_line = signal_series[-1]
    if signal_line is None:
        return None, None, None
    return macd_line, signal_line, macd_line - signal_line


def bollinger_bands(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[float | None, float | None, float | None]:
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance**0.5
    return mean + num_std * std, mean, mean - num_std * std


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(closes)):
        high, low, prev_close = highs[i], lows[i], closes[i - 1]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    avg_tr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        avg_tr = (avg_tr * (period - 1) + tr) / period
    return avg_tr
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_indicators.py -v`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/indicators.py tests/technical/test_indicators.py
git commit -m "Add pure-Python RSI/MACD/Bollinger/EMA/ATR indicator functions"
```

---

### Task 3: Klines fetcher

**Files:**
- Create: `src/hello_coin/technical/klines.py`
- Test: `tests/technical/test_klines.py`

**Verified live:** `curl "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=3"`
returned a real array-of-arrays response, e.g.
`[[1787367600000,"78467.90","78831.80","78344.30","78395.00","6088.611",1787371199999,...]]` —
`[openTime, open, high, low, close, volume, closeTime, ...]`, confirming the endpoint, no-auth
access, and field order (same `fapi.binance.com` host already used by the exchange derivatives
adapters in `ingestion/adapters/binance.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/technical/test_klines.py`:

```python
import httpx
import pytest
import respx

from hello_coin.technical.klines import BINANCE_KLINES_URL, fetch_klines
from hello_coin.technical.models import Candle

KLINES_RESPONSE = [
    [
        1787367600000,
        "78467.90",
        "78831.80",
        "78344.30",
        "78395.00",
        "6088.611",
        1787371199999,
        "478553147.28660",
        187608,
        "3012.611",
        "236819326.95900",
        "0",
    ],
    [
        1787371200000,
        "78395.00",
        "78815.20",
        "78183.10",
        "78453.30",
        "5979.954",
        1787374799999,
        "469471517.23890",
        197325,
        "2972.938",
        "233391676.12620",
        "0",
    ],
]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_klines_parses_response_into_candles():
    respx.get(BINANCE_KLINES_URL).mock(return_value=httpx.Response(200, json=KLINES_RESPONSE))

    candles = await fetch_klines("BTCUSDT", "1h", 2)

    assert len(candles) == 2
    candle = candles[0]
    assert isinstance(candle, Candle)
    assert candle.open == 78467.90
    assert candle.high == 78831.80
    assert candle.low == 78344.30
    assert candle.close == 78395.00
    assert candle.volume == 6088.611


@pytest.mark.asyncio
@respx.mock
async def test_fetch_klines_sends_symbol_interval_limit_params():
    route = respx.get(BINANCE_KLINES_URL).mock(
        return_value=httpx.Response(200, json=KLINES_RESPONSE)
    )

    await fetch_klines("ETHUSDT", "4h", 50)

    params = route.calls[0].request.url.params
    assert params["symbol"] == "ETHUSDT"
    assert params["interval"] == "4h"
    assert params["limit"] == "50"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_klines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.klines'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/technical/klines.py`:

```python
from datetime import UTC, datetime

import httpx

from hello_coin.technical.models import Candle

BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


async def fetch_klines(symbol: str, interval: str, limit: int) -> list[Candle]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        rows = response.json()
        return [
            Candle(
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_klines.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/klines.py tests/technical/test_klines.py
git commit -m "Add Binance klines fetcher"
```

---

### Task 4: Snapshot service

**Files:**
- Create: `src/hello_coin/technical/service.py`
- Test: `tests/technical/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/technical/test_service.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.technical.models import Candle
from hello_coin.technical.service import DEFAULT_CANDLE_LIMIT, compute_snapshot


def _candle(i: int) -> Candle:
    price = 100.0 + i
    return Candle(
        open_time=datetime.fromtimestamp(1_700_000_000 + i * 3600, tz=UTC),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=10.0,
    )


@pytest.mark.asyncio
async def test_compute_snapshot_combines_fetch_and_indicators():
    # MACD(fast=12, slow=26, signal=9) needs at least slow + signal - 1 = 34 candles
    # before its macd-line series is long enough to produce a non-None signal —
    # fewer candles than that would leave macd_line/signal/histogram all None even
    # though RSI/Bollinger/EMA/ATR (which need at most 20) would already be populated.
    candles = [_candle(i) for i in range(40)]
    with patch(
        "hello_coin.technical.service.fetch_klines", new=AsyncMock(return_value=candles)
    ) as mock_fetch:
        snapshot = await compute_snapshot("BTCUSDT", "1h")

    mock_fetch.assert_awaited_once_with("BTCUSDT", "1h", DEFAULT_CANDLE_LIMIT)
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.timeframe == "1h"
    assert snapshot.close_price == candles[-1].close
    assert snapshot.timestamp == candles[-1].open_time
    # 40 candles is enough history for every indicator to be non-None.
    assert snapshot.rsi is not None
    assert snapshot.macd_line is not None
    assert snapshot.bb_upper is not None
    assert snapshot.ema is not None
    assert snapshot.atr is not None


@pytest.mark.asyncio
async def test_compute_snapshot_leaves_indicators_none_with_short_history():
    candles = [_candle(i) for i in range(5)]
    with patch("hello_coin.technical.service.fetch_klines", new=AsyncMock(return_value=candles)):
        snapshot = await compute_snapshot("BTCUSDT", "1h")

    assert snapshot.rsi is None
    assert snapshot.macd_line is None
    assert snapshot.bb_upper is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.service'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/technical/service.py`:

```python
from hello_coin.technical.indicators import atr, bollinger_bands, ema, macd, rsi
from hello_coin.technical.klines import fetch_klines
from hello_coin.technical.models import IndicatorSnapshot

DEFAULT_CANDLE_LIMIT = 100
EMA_PERIOD = 20
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BOLLINGER_PERIOD = 20
ATR_PERIOD = 14


async def compute_snapshot(symbol: str, timeframe: str) -> IndicatorSnapshot:
    candles = await fetch_klines(symbol, timeframe, DEFAULT_CANDLE_LIMIT)
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    macd_line, macd_signal, macd_histogram = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    bb_upper, bb_middle, bb_lower = bollinger_bands(closes, BOLLINGER_PERIOD, 2.0)
    latest = candles[-1]

    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=latest.open_time,
        close_price=latest.close,
        rsi=rsi(closes, RSI_PERIOD),
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_histogram=macd_histogram,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        ema=ema(closes, EMA_PERIOD),
        atr=atr(highs, lows, closes, ATR_PERIOD),
        raw={"candle_count": len(candles)},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_service.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/service.py tests/technical/test_service.py
git commit -m "Add technical-indicators snapshot service"
```

---

### Task 5: SQLite storage

**Files:**
- Create: `src/hello_coin/technical/storage.py`
- Test: `tests/technical/test_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/technical/test_storage.py`:

```python
from datetime import UTC, datetime

from hello_coin.technical.models import IndicatorSnapshot
from hello_coin.technical.storage import TechnicalStorage


def _snapshot(timestamp: datetime) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=timestamp,
        close_price=100.0,
        rsi=55.0,
        macd_line=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        ema=99.0,
        atr=2.0,
        raw={"candle_count": 100},
    )


def test_insert_snapshot_returns_count_and_dedupes():
    storage = TechnicalStorage(":memory:")
    first = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timeframe/timestamp
    third = _snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC))

    inserted_first = storage.insert_snapshot(first)
    inserted_second = storage.insert_snapshot(second)
    inserted_third = storage.insert_snapshot(third)

    assert inserted_first == 1
    assert inserted_second == 0
    assert inserted_third == 1
    assert storage.count_snapshots() == 2
    assert storage.count_snapshots(symbol="BTCUSDT") == 2
    assert storage.count_snapshots(symbol="ETHUSDT") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.storage'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/technical/storage.py`:

```python
import json
import sqlite3
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_storage.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/storage.py tests/technical/test_storage.py
git commit -m "Add SQLite-backed TechnicalStorage with dedup on insert"
```

---

### Task 6: Scheduler

**Files:**
- Create: `src/hello_coin/technical/scheduler.py`
- Test: `tests/technical/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/technical/test_scheduler.py`:

```python
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hello_coin.technical.models import IndicatorSnapshot
from hello_coin.technical.scheduler import poll_once, run_symbol_loop
from hello_coin.technical.storage import TechnicalStorage


def _snapshot() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        close_price=100.0,
        rsi=55.0,
        macd_line=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        ema=99.0,
        atr=2.0,
        raw={},
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_snapshot_and_returns_count():
    storage = TechnicalStorage(":memory:")
    with patch(
        "hello_coin.technical.scheduler.compute_snapshot",
        new=AsyncMock(return_value=_snapshot()),
    ):
        inserted = await poll_once("BTCUSDT", "1h", storage)

    assert inserted == 1
    assert storage.count_snapshots() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_fetch_failure(caplog):
    storage = TechnicalStorage(":memory:")
    with patch(
        "hello_coin.technical.scheduler.compute_snapshot",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once("BTCUSDT", "1h", storage)

    assert inserted == 0
    assert storage.count_snapshots() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = TechnicalStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_snapshot(symbol, timeframe):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _snapshot()

    with patch(
        "hello_coin.technical.scheduler.compute_snapshot", new=_fake_compute_snapshot
    ):
        await run_symbol_loop("BTCUSDT", "1h", storage, stop_event, poll_interval_seconds=0)

    assert call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/technical/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.technical.scheduler'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/technical/scheduler.py`:

```python
import asyncio
import logging

from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

logger = logging.getLogger(__name__)


async def poll_once(symbol: str, timeframe: str, storage: TechnicalStorage) -> int:
    try:
        snapshot = await compute_snapshot(symbol, timeframe)
    except Exception:
        logger.exception("%s: technical snapshot fetch failed", symbol)
        return 0
    return storage.insert_snapshot(snapshot)


async def run_symbol_loop(
    symbol: str,
    timeframe: str,
    storage: TechnicalStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(symbol, timeframe, storage)
        logger.info("%s: inserted %d new row(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str], timeframe: str, storage: TechnicalStorage, poll_interval_seconds: int = 900
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(symbol, timeframe, storage, stop_event, poll_interval_seconds)
            for symbol in symbols
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/technical/test_scheduler.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/technical/scheduler.py tests/technical/test_scheduler.py
git commit -m "Add technical-indicators scheduler"
```

---

### Task 7: Config and CLI wiring

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `src/hello_coin/cli.py`
- Modify: `tests/ingestion/test_config.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_config.py`:

```python
def test_technical_timeframe_defaults_to_1h(monkeypatch):
    monkeypatch.delenv("TECHNICAL_TIMEFRAME", raising=False)

    settings = Settings(_env_file=None)

    assert settings.technical_timeframe == "1h"


def test_technical_timeframe_reads_from_env(monkeypatch):
    monkeypatch.setenv("TECHNICAL_TIMEFRAME", "4h")

    settings = Settings(_env_file=None)

    assert settings.technical_timeframe == "4h"
```

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py tests/test_cli.py -v`
Expected: FAIL — `technical_timeframe` doesn't exist on `Settings`; `technical` isn't a valid
subcommand yet.

- [ ] **Step 3: Write the implementation**

In `src/hello_coin/ingestion/config.py`, add one field to `Settings` (after
`bitquery_min_value_usd`):

```python
    technical_timeframe: str = "1h"
```

(No validator changes needed — it's a plain string, not a comma-separated list.)

Replace the contents of `src/hello_coin/cli.py`:

```python
import argparse
import asyncio
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py tests/test_cli.py -v`
Expected: all pass (12 config tests, 4 CLI tests).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/config.py src/hello_coin/cli.py tests/ingestion/test_config.py tests/test_cli.py
git commit -m "Wire technical-indicators config and CLI commands"
```

---

### Task 8: Real-network smoke test, docs, and manual verification

**Files:**
- Create: `tests/technical/test_klines_smoke.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `.gitignore` (if `data/technical.db` isn't already covered — it is, `data/` is already
  ignored from the ingestion plan, so no change needed; verify during this task rather than
  assume)

- [ ] **Step 1: Write the network smoke test**

Create `tests/technical/test_klines_smoke.py`:

```python
import pytest

from hello_coin.technical.service import compute_snapshot


@pytest.mark.network
@pytest.mark.asyncio
async def test_compute_snapshot_reaches_real_binance_api():
    snapshot = await compute_snapshot("BTCUSDT", "1h")

    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.close_price > 0
    # 100 candles (DEFAULT_CANDLE_LIMIT) is enough history for every indicator.
    assert snapshot.rsi is not None
    assert snapshot.macd_line is not None
    assert snapshot.bb_upper is not None
```

- [ ] **Step 2: Run it against the real API**

Run: `uv run pytest tests/technical/test_klines_smoke.py -m network -v`
Expected: `1 passed` (confirms the real Binance klines endpoint is reachable and the full
fetch → compute pipeline runs end to end against real data).

- [ ] **Step 3: Verify `.gitignore` already covers `data/`**

Run: `grep -n "^data/" .gitignore`
Expected: one match (added during the whale-ingestion framework plan) — no edit needed here.

- [ ] **Step 4: Commit the smoke test**

```bash
git add tests/technical/test_klines_smoke.py
git commit -m "Add network-marked smoke test for the technical-indicators pipeline"
```

- [ ] **Step 5: Update CLAUDE.md**

In `CLAUDE.md`, in the `## Architecture` section, after the `ingestion/` bullet list (before
`src/hello_coin/cli.py is the entry point...`), add:

```markdown
`src/hello_coin/technical/` is the technical-indicators layer (the 30%-weighted signal), see
`docs/superpowers/specs/2026-08-22-technical-indicators-design.md`:

- `models.py` — `Candle` and `IndicatorSnapshot` (all indicator fields `float | None`; `None`
  means not enough history yet, never a fabricated number).
- `indicators.py` — pure functions: `rsi()`, `macd()`, `bollinger_bands()`, `ema()`, `atr()`.
  No HTTP, no models — testable against hand-verified reference values with zero mocking.
- `klines.py` — fetches OHLCV candles from Binance's public futures klines endpoint (no key).
- `service.py` — combines `klines.py` + `indicators.py` into one `IndicatorSnapshot`.
- `storage.py` — SQLite (`data/technical.db`, gitignored) with dedup on
  `(symbol, timeframe, timestamp)`.
- `scheduler.py` — polls every symbol in `exchange_watch_symbols` every 15 minutes. No
  `Adapter`-style registry — there's one data source here, not many.
```

Update the CLI entry-point sentence to:

```markdown
`src/hello_coin/cli.py` is the entry point: `hello-coin ingest run` / `hello-coin technical run`
start the two services, `hello-coin ingest test <source>` / `hello-coin technical test <symbol>`
fetch or compute once and print the result.
```

- [ ] **Step 6: Update README.md**

In `README.md`, add a new section after `## Whale ingestion`:

```markdown
## Technical indicators

1. No extra config needed — reuses `EXCHANGE_WATCH_SYMBOLS` from whale ingestion (default
   `BTCUSDT`) and defaults `TECHNICAL_TIMEFRAME` to `1h`.
2. Fetch once to sanity-check it: `uv run hello-coin technical test BTCUSDT`
3. Run the service continuously: `uv run hello-coin technical run` — writes to
   `data/technical.db`.
```

- [ ] **Step 7: Manually verify against the real Binance API**

```bash
uv run hello-coin technical test BTCUSDT
```

Expected: prints one `IndicatorSnapshot(...)` line with real, non-`None` `rsi`/`macd_line`/
`bb_upper`/`ema`/`atr` values.

```bash
uv run hello-coin technical run
```

Let it run for a few seconds, then stop it (Ctrl+C). Expected: a log line like
`BTCUSDT: inserted 1 new row(s)`, and `data/technical.db` exists.

- [ ] **Step 8: Run the full test suite one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the technical-indicators module and how to run it"
```
