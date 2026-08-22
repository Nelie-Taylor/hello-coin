# Exchange Derivatives Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four new whale-metric adapters — Binance, OKX, Bybit, Bitget — that poll each
exchange's public (no-API-key) long/short account-ratio endpoint and wire them into the existing
registry/scheduler/storage framework built in
`docs/superpowers/plans/2026-08-22-whale-ingestion-framework-hyperliquid.md`.

**Architecture:** Same adapter pattern as Hyperliquid, per
`docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md`. Each of the four adapters
produces `WhaleMetric` rows (aggregate, not per-wallet) instead of `WhaleEvent` rows. All four
endpoints require no authentication, so every adapter is "configured" whenever its watch-symbol
list is non-empty — which it is by default (`["BTCUSDT"]`), so the service picks these four up
with zero `.env` setup. All four endpoints were manually verified live via `curl` while writing
this plan (see per-task "Verified live" notes) — none of the request/response shapes below are
guessed.

**Tech Stack:** Same as the framework plan — `httpx` (async HTTP), `pydantic-settings`,
`pytest` + `pytest-asyncio` + `respx`.

---

### Task 1: Shared `exchange_watch_symbols` setting

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `.env.example`
- Modify: `tests/ingestion/test_config.py`

All four exchange adapters watch the same list of symbols (default `["BTCUSDT"]`), reusing the
comma-split parsing already written for `hyperliquid_watch_addresses`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ingestion/test_config.py` (append to the existing file, keep the two Hyperliquid
tests as-is):

```python
def test_exchange_watch_symbols_defaults_to_btcusdt(monkeypatch):
    monkeypatch.delenv("EXCHANGE_WATCH_SYMBOLS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT"]


def test_exchange_watch_symbols_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("EXCHANGE_WATCH_SYMBOLS", "BTCUSDT, ETHUSDT ,SOLUSDT")

    settings = Settings(_env_file=None)

    assert settings.exchange_watch_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'exchange_watch_symbols'`
on the two new tests; the two pre-existing Hyperliquid tests still pass.

- [ ] **Step 3: Write the implementation**

In `src/hello_coin/ingestion/config.py`, replace the whole file with:

```python
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Ingestion config. Every adapter's credentials are optional here — a
    missing key means that adapter reports itself as not configured and is
    skipped, not that the app fails to start."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hyperliquid_watch_addresses: Annotated[list[str], NoDecode] = []
    exchange_watch_symbols: Annotated[list[str], NoDecode] = ["BTCUSDT"]

    @field_validator("hyperliquid_watch_addresses", "exchange_watch_symbols", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
```

Edit `.env.example`, append:

```
# Comma-separated symbols to poll on Binance/OKX/Bybit/Bitget for long/short account-ratio
# data. No API key needed. Defaults to BTCUSDT if unset.
EXCHANGE_WATCH_SYMBOLS=BTCUSDT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/config.py .env.example tests/ingestion/test_config.py
git commit -m "Add shared exchange_watch_symbols setting"
```

---

### Task 2: Binance adapter

**Files:**
- Create: `src/hello_coin/ingestion/adapters/binance.py`
- Test: `tests/ingestion/test_binance.py`

**Verified live:** `curl "https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=5m&limit=1"`
returned:
```json
[{"symbol":"BTCUSDT","longAccount":"0.6647","longShortRatio":"1.9823","shortAccount":"0.3353","timestamp":1787372700000}]
```
This is Binance's official "Top Trader Long/Short Ratio (Positions)" endpoint — a direct
whale-proxy metric (top 20% of accounts by margin balance), matching the design spec's Binance
entry.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_binance.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.binance import BINANCE_TOP_LS_RATIO_URL, BinanceAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = [
    {
        "symbol": "BTCUSDT",
        "longAccount": "0.6647",
        "longShortRatio": "1.9823",
        "shortAccount": "0.3353",
        "timestamp": 1787372700000,
    }
]


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BinanceAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BinanceAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_ratio_into_whale_metric():
    respx.get(BINANCE_TOP_LS_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BinanceAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "binance"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "top_trader_long_short_ratio"
    assert metric.value == 1.9823
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    respx.get(BINANCE_TOP_LS_RATIO_URL).mock(return_value=httpx.Response(200, json=[]))
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BinanceAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_binance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.binance'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/binance.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BINANCE_TOP_LS_RATIO_URL = "https://fapi.binance.com/futures/data/topLongShortPositionRatio"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["timestamp"])
    return WhaleMetric(
        source="binance",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="top_trader_long_short_ratio",
        value=float(row["longShortRatio"]),
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BinanceAdapter(Adapter):
    """Polls Binance Futures' public Top Trader Long/Short Ratio (Positions)
    endpoint — the top 20% of accounts by margin balance, a direct whale
    proxy. No API key needed.
    """

    name = "binance"
    poll_interval_seconds = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.exchange_watch_symbols)

    async def fetch(self) -> list[WhaleMetric]:
        metrics: list[WhaleMetric] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in self._settings.exchange_watch_symbols:
                response = await client.get(
                    BINANCE_TOP_LS_RATIO_URL,
                    params={"symbol": symbol, "period": "5m", "limit": 1},
                )
                response.raise_for_status()
                rows = response.json()
                if not rows:
                    continue
                metrics.append(_parse_ratio(symbol, rows[0]))
        return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_binance.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/binance.py tests/ingestion/test_binance.py
git commit -m "Add Binance top-trader long/short ratio adapter"
```

---

### Task 3: OKX adapter

**Files:**
- Create: `src/hello_coin/ingestion/adapters/okx.py`
- Test: `tests/ingestion/test_okx.py`

**Verified live:** `curl "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio-contract?instId=BTC-USDT-SWAP&limit=1"`
returned:
```json
{"code":"0","data":[["1787372700000","1.2740831113213654"]],"msg":""}
```
`data` is a list of `[timestamp_ms_string, ratio_string]` pairs, not objects — different shape
than Binance. OKX's public API uses `instId` values like `BTC-USDT-SWAP`, not `BTCUSDT`, so this
adapter converts the shared `exchange_watch_symbols` entries (e.g. `BTCUSDT`) into that format.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_okx.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.okx import (
    OKX_LONG_SHORT_RATIO_URL,
    OkxAdapter,
    to_okx_inst_id,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "code": "0",
    "data": [
        ["1787372700000", "1.2740831113213654"],
        ["1787372400000", "1.2745161531372207"],
    ],
    "msg": "",
}


def test_to_okx_inst_id_converts_usdt_pair():
    assert to_okx_inst_id("BTCUSDT") == "BTC-USDT-SWAP"


def test_to_okx_inst_id_rejects_non_usdt_pair():
    with pytest.raises(ValueError, match="BTCBUSD"):
        to_okx_inst_id("BTCBUSD")


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = OkxAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = OkxAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_latest_ratio_into_whale_metric():
    respx.get(OKX_LONG_SHORT_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = OkxAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "okx"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    assert metric.value == 1.2740831113213654
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    respx.get(OKX_LONG_SHORT_RATIO_URL).mock(
        return_value=httpx.Response(200, json={"code": "0", "data": [], "msg": ""})
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = OkxAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_okx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.okx'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/okx.py`:

```python
from datetime import UTC, datetime

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

OKX_LONG_SHORT_RATIO_URL = (
    "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio-contract"
)


def to_okx_inst_id(symbol: str) -> str:
    if not symbol.endswith("USDT"):
        raise ValueError(f"unsupported symbol for OKX conversion: {symbol}")
    base = symbol[: -len("USDT")]
    return f"{base}-USDT-SWAP"


class OkxAdapter(Adapter):
    """Polls OKX's public long/short account-ratio endpoint for USDT-margined
    swaps. No API key needed.
    """

    name = "okx"
    poll_interval_seconds = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.exchange_watch_symbols)

    async def fetch(self) -> list[WhaleMetric]:
        metrics: list[WhaleMetric] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in self._settings.exchange_watch_symbols:
                inst_id = to_okx_inst_id(symbol)
                response = await client.get(
                    OKX_LONG_SHORT_RATIO_URL, params={"instId": inst_id, "limit": 1}
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                if not rows:
                    continue
                latest = max(rows, key=lambda row: int(row[0]))
                timestamp_ms = int(latest[0])
                metrics.append(
                    WhaleMetric(
                        source="okx",
                        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
                        symbol=symbol,
                        metric_name="long_short_account_ratio",
                        value=float(latest[1]),
                        dedup_key=f"{symbol}:{timestamp_ms}",
                        raw={"instId": inst_id, "timestamp": latest[0], "ratio": latest[1]},
                    )
                )
        return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_okx.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/okx.py tests/ingestion/test_okx.py
git commit -m "Add OKX long/short account-ratio adapter"
```

---

### Task 4: Bybit adapter

**Files:**
- Create: `src/hello_coin/ingestion/adapters/bybit.py`
- Test: `tests/ingestion/test_bybit.py`

**Verified live:** `curl "https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=5min&limit=1"`
returned:
```json
{"retCode":0,"retMsg":"OK","result":{"list":[{"symbol":"BTCUSDT","buyRatio":"0.5395","sellRatio":"0.4605","timestamp":"1787372700000"}],"nextPageCursor":"..."},"retExtInfo":{},"time":1787372829259}
```
Bybit reports `buyRatio`/`sellRatio` (which sum to ~1.0) rather than a combined ratio field, so
this adapter derives `value = buyRatio / sellRatio` to match the `long_short_account_ratio`
convention used by the other adapters.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_bybit.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bybit import BYBIT_ACCOUNT_RATIO_URL, BybitAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "list": [
            {"symbol": "BTCUSDT", "buyRatio": "0.5395", "sellRatio": "0.4605", "timestamp": "1787372700000"}
        ],
        "nextPageCursor": "lastid=0&lasttime=1787372700",
    },
    "retExtInfo": {},
    "time": 1787372829259,
}


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BybitAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BybitAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_ratio_into_whale_metric():
    respx.get(BYBIT_ACCOUNT_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BybitAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "bybit"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    assert metric.value == pytest.approx(0.5395 / 0.4605)
    assert metric.dedup_key == "BTCUSDT:1787372700000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    empty_response = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": [], "nextPageCursor": ""},
        "retExtInfo": {},
        "time": 1787372829259,
    }
    respx.get(BYBIT_ACCOUNT_RATIO_URL).mock(return_value=httpx.Response(200, json=empty_response))
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BybitAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_bybit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.bybit'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/bybit.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BYBIT_ACCOUNT_RATIO_URL = "https://api.bybit.com/v5/market/account-ratio"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["timestamp"])
    buy_ratio = float(row["buyRatio"])
    sell_ratio = float(row["sellRatio"])
    value = buy_ratio / sell_ratio if sell_ratio else 0.0
    return WhaleMetric(
        source="bybit",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="long_short_account_ratio",
        value=value,
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BybitAdapter(Adapter):
    """Polls Bybit's public account long/short ratio endpoint for linear
    (USDT-margined) perps. No API key needed.
    """

    name = "bybit"
    poll_interval_seconds = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.exchange_watch_symbols)

    async def fetch(self) -> list[WhaleMetric]:
        metrics: list[WhaleMetric] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in self._settings.exchange_watch_symbols:
                response = await client.get(
                    BYBIT_ACCOUNT_RATIO_URL,
                    params={"category": "linear", "symbol": symbol, "period": "5min", "limit": 1},
                )
                response.raise_for_status()
                rows = response.json().get("result", {}).get("list", [])
                if not rows:
                    continue
                metrics.append(_parse_ratio(symbol, rows[0]))
        return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_bybit.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/bybit.py tests/ingestion/test_bybit.py
git commit -m "Add Bybit account long/short ratio adapter"
```

---

### Task 5: Bitget adapter

**Files:**
- Create: `src/hello_coin/ingestion/adapters/bitget.py`
- Test: `tests/ingestion/test_bitget.py`

**Verified live:** `curl "https://api.bitget.com/api/v2/mix/market/account-long-short?symbol=BTCUSDT&productType=USDT-FUTURES&period=5m"`
returned a `data` array of ~30 rows shaped
`{"longAccountRatio","shortAccountRatio","longShortAccountRatio","ts"}`, in ascending timestamp
order. Unlike the other three exchanges, Bitget's endpoint **ignores a `limit` param** — adding
`limit=1` still returned all ~30 rows in testing — so this adapter must not assume the response
is small or already sorted; it explicitly selects the max-timestamp row.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_bitget.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bitget import (
    BITGET_ACCOUNT_LONG_SHORT_URL,
    BitgetAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "code": "00000",
    "msg": "success",
    "requestTime": 1787372828693,
    "data": [
        {
            "longAccountRatio": "0.5676",
            "shortAccountRatio": "0.4324",
            "longShortAccountRatio": "1.3126",
            "ts": "1787372100000",
        },
        {
            "longAccountRatio": "0.5673",
            "shortAccountRatio": "0.4327",
            "longShortAccountRatio": "1.311",
            "ts": "1787372400000",
        },
    ],
}


def test_is_configured_true_by_default():
    settings = Settings()
    adapter = BitgetAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_symbols():
    settings = Settings(exchange_watch_symbols=[])
    adapter = BitgetAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_selects_max_timestamp_row_regardless_of_order():
    respx.get(BITGET_ACCOUNT_LONG_SHORT_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BitgetAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "bitget"
    assert metric.symbol == "BTCUSDT"
    assert metric.metric_name == "long_short_account_ratio"
    # RATIO_RESPONSE[1] has the larger "ts" despite being listed second —
    # the adapter must pick it by value, not by list position.
    assert metric.value == 1.311
    assert metric.dedup_key == "BTCUSDT:1787372400000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_api_returns_no_rows():
    empty_response = {"code": "00000", "msg": "success", "requestTime": 1, "data": []}
    respx.get(BITGET_ACCOUNT_LONG_SHORT_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = BitgetAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_bitget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.bitget'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/bitget.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

BITGET_ACCOUNT_LONG_SHORT_URL = "https://api.bitget.com/api/v2/mix/market/account-long-short"


def _parse_ratio(symbol: str, row: dict[str, Any]) -> WhaleMetric:
    timestamp_ms = int(row["ts"])
    return WhaleMetric(
        source="bitget",
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        symbol=symbol,
        metric_name="long_short_account_ratio",
        value=float(row["longShortAccountRatio"]),
        dedup_key=f"{symbol}:{timestamp_ms}",
        raw=row,
    )


class BitgetAdapter(Adapter):
    """Polls Bitget's public account long/short ratio endpoint for USDT
    futures. No API key needed. The endpoint ignores `limit`, so this
    explicitly picks the max-timestamp row rather than assuming order.
    """

    name = "bitget"
    poll_interval_seconds = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.exchange_watch_symbols)

    async def fetch(self) -> list[WhaleMetric]:
        metrics: list[WhaleMetric] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for symbol in self._settings.exchange_watch_symbols:
                response = await client.get(
                    BITGET_ACCOUNT_LONG_SHORT_URL,
                    params={"symbol": symbol, "productType": "USDT-FUTURES", "period": "5m"},
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                if not rows:
                    continue
                latest = max(rows, key=lambda row: int(row["ts"]))
                metrics.append(_parse_ratio(symbol, latest))
        return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_bitget.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/bitget.py tests/ingestion/test_bitget.py
git commit -m "Add Bitget account long/short ratio adapter"
```

---

### Task 6: Wire all four into the registry

**Files:**
- Modify: `src/hello_coin/ingestion/registry.py`
- Modify: `tests/ingestion/test_registry.py`

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/ingestion/test_registry.py`:

```python
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters


def test_build_adapters_includes_all_configured_sources():
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid", "binance", "okx", "bybit", "bitget"]


def test_build_adapters_skips_unconfigured_hyperliquid_but_keeps_exchange_adapters(caplog):
    settings = Settings(hyperliquid_watch_addresses=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["binance", "okx", "bybit", "bitget"]
    assert "hyperliquid" in caplog.text


def test_build_adapters_skips_all_exchange_adapters_when_no_symbols(caplog):
    settings = Settings(hyperliquid_watch_addresses=["0xabc"], exchange_watch_symbols=[])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ["hyperliquid"]
    for exchange in ("binance", "okx", "bybit", "bitget"):
        assert exchange in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: FAIL — `test_build_adapters_includes_all_configured_sources` fails because
`build_adapters` still only returns `["hyperliquid"]`.

- [ ] **Step 3: Write the implementation**

Replace the contents of `src/hello_coin/ingestion/registry.py`:

```python
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.adapters.okx import OkxAdapter
from hello_coin.ingestion.config import Settings

logger = logging.getLogger(__name__)


def build_adapters(settings: Settings) -> list[Adapter]:
    """Return every adapter that reports itself as configured, logging a
    warning for each one that's skipped. Add new adapters to `candidates`
    here as they're implemented."""

    candidates: list[Adapter] = [
        HyperliquidAdapter(settings),
        BinanceAdapter(settings),
        OkxAdapter(settings),
        BybitAdapter(settings),
        BitgetAdapter(settings),
    ]

    configured: list[Adapter] = []
    for adapter in candidates:
        if adapter.is_configured():
            configured.append(adapter)
        else:
            logger.warning("%s: not configured, skipping", adapter.name)
    return configured
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: `3 passed`

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (framework tests + all five adapters' tests).

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/registry.py tests/ingestion/test_registry.py
git commit -m "Wire Binance/OKX/Bybit/Bitget adapters into the registry"
```

---

### Task 7: Real-API smoke tests, docs, and manual end-to-end verification

**Files:**
- Create: `tests/ingestion/test_exchange_smoke.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Write the network smoke tests**

Create `tests/ingestion/test_exchange_smoke.py`:

```python
import pytest

from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.okx import OkxAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

ADAPTER_CLASSES = [BinanceAdapter, OkxAdapter, BybitAdapter, BitgetAdapter]


@pytest.mark.network
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_cls", ADAPTER_CLASSES, ids=[c.name for c in ADAPTER_CLASSES])
async def test_fetch_reaches_real_exchange_api(adapter_cls):
    settings = Settings(exchange_watch_symbols=["BTCUSDT"])
    adapter = adapter_cls(settings)

    metrics = await adapter.fetch()

    assert isinstance(metrics, list)
    assert len(metrics) == 1
    assert all(isinstance(metric, WhaleMetric) for metric in metrics)
```

- [ ] **Step 2: Run it against the real APIs**

Run: `uv run pytest tests/ingestion/test_exchange_smoke.py -m network -v`
Expected: `4 passed` (confirms all four real endpoints are reachable and their response shapes
still match what each adapter's parser expects; not run by plain `uv run pytest`).

- [ ] **Step 3: Commit**

```bash
git add tests/ingestion/test_exchange_smoke.py
git commit -m "Add network-marked smoke tests for exchange derivatives adapters"
```

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, in the `## Architecture` section, replace:

```
- `adapters/*.py` — one file per data source. Only `hyperliquid.py` exists so far.
```

with:

```
- `adapters/*.py` — one file per data source: `hyperliquid.py` (per-wallet fills), and
  `binance.py`/`okx.py`/`bybit.py`/`bitget.py` (public long/short account-ratio metrics, no API
  key needed).
```

- [ ] **Step 5: Update README.md**

In `README.md`, in the `## Whale ingestion` section, replace:

```markdown
1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
2. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
3. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.
```

with:

```markdown
1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
   `EXCHANGE_WATCH_SYMBOLS` defaults to `BTCUSDT` and needs no key — the Binance/OKX/Bybit/Bitget
   adapters work out of the box.
2. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
   (or `binance`, `okx`, `bybit`, `bitget`).
3. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.
```

- [ ] **Step 6: Manually verify against the real exchange APIs**

```bash
uv run hello-coin ingest test binance
uv run hello-coin ingest test okx
uv run hello-coin ingest test bybit
uv run hello-coin ingest test bitget
```

Expected: each prints one `WhaleMetric(...)` line with a plausible `value` (a ratio around
0.5–3.0 for BTCUSDT under normal market conditions).

Then run the full service for ~30 seconds and confirm all five sources log inserts:

```bash
uv run hello-coin ingest run
```

Expected: log lines like `binance: inserted 1 new row(s)`, `okx: inserted 1 new row(s)`, etc.,
alongside the existing `hyperliquid: inserted N new row(s)` line.

- [ ] **Step 7: Run the full test suite one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the exchange derivatives adapters"
```
