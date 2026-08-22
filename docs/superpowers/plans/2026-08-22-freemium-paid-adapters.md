# Freemium/Paid Whale Data Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add adapters for the remaining verifiable freemium/paid whale data sources: DeBank
Cloud, CryptoQuant, Nansen, Whale Alert, and Bitquery. All five require a paid or freemium API
key the user does not yet hold, so none of them can be smoke-tested live in this environment —
every endpoint/auth/response shape below was independently verified via official docs and/or
live unauthenticated `curl` requests (confirming the endpoint is real and how it rejects missing
auth) before being used in code, per this project's no-guessed-code standard. Confidence level is
called out per adapter.

**Architecture:** Same adapter pattern as before. Two sources are dropped/deferred this round —
see "Deferred" below.

**Confidence per adapter:**
- **DeBank, CryptoQuant, Nansen — fully verified.** Endpoint, auth, and response schema
  confirmed directly against official docs (DeBank, CryptoQuant via its own OpenAPI spec) or
  independently confirmed via a live request whose error body echoes the documented schema
  (Nansen's 402 response body includes the exact field names from its docs).
- **Whale Alert, Bitquery — request/auth verified live; response shape lower-confidence.** Base
  URL, auth mechanism, and query parameters are confirmed via live `curl` (both return
  structured, parameter-aware error bodies, not generic 404s). The success-response field names
  come from secondhand sources (search-engine synthesis / third-party doc mirrors, not a directly
  fetched first-party JSON sample) because the official docs pages render JS-only content this
  environment can't extract. Both adapters therefore parse defensively (`dict.get(...)` with
  `None` fallbacks, never a bare `row["field"]` that would `KeyError` on an unexpected shape) and
  their tests are written against the most-likely field names with this caveat documented in the
  adapter's docstring. If a real key later reveals different field names, only that adapter's
  parse function needs fixing — the rest of the framework is unaffected.

**Deferred — not implemented this round (insufficient verification):**
- **Solscan**: base URL (`pro-api.solscan.io/v2.0`), the `token` auth header, and paid-only
  status ($49/mo minimum, no free tier) are confirmed. The exact request/response shape for the
  account-transactions endpoint is not documented anywhere fetchable — the official docs page
  only names the endpoint category, not its parameters or response fields. Writing a parser here
  would mean guessing field names with no source at all (unlike Whale Alert/Bitquery above, where
  secondhand sources at least exist). Deferred until the real docs (or a paid account) are
  available.
- **Arkham**: the base URL and one endpoint path (`GET /balances/address/{address}`) are
  live-confirmed, but auth is a 3-header HMAC-signed-request scheme (`API-Key`,
  `API-Timestamp`, `API-Signature`) whose signing algorithm isn't documented anywhere fetchable.
  Guessing an HMAC scheme would produce code that looks plausible but silently signs requests
  wrong — worse than an honest "not implemented." Deferred until official signing docs or the
  user's own working example is available.
- **ClankApp**: already deferred in
  `docs/superpowers/plans/2026-08-22-etherscan-adapter.md` — still unverified as of this plan.

**Tech Stack:** Same as prior adapters — `httpx`, `pydantic-settings`, `pytest` +
`pytest-asyncio` + `respx`.

---

### Task 1: Settings for all five sources

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `.env.example`
- Modify: `tests/ingestion/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_config.py`:

```python
def test_freemium_settings_default_to_unconfigured(monkeypatch):
    for var in (
        "DEBANK_ACCESS_KEY",
        "DEBANK_WATCH_ADDRESSES",
        "CRYPTOQUANT_API_KEY",
        "NANSEN_API_KEY",
        "NANSEN_WATCH_ADDRESSES",
        "WHALE_ALERT_API_KEY",
        "BITQUERY_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.debank_access_key is None
    assert settings.debank_watch_addresses == []
    assert settings.cryptoquant_api_key is None
    assert settings.nansen_api_key is None
    assert settings.nansen_watch_addresses == []
    assert settings.whale_alert_api_key is None
    assert settings.whale_alert_min_value_usd == 500_000
    assert settings.bitquery_access_token is None
    assert settings.bitquery_min_value_usd == 500_000


def test_debank_and_nansen_watch_addresses_parse_comma_separated(monkeypatch):
    monkeypatch.setenv("DEBANK_WATCH_ADDRESSES", "0xaaa, 0xbbb")
    monkeypatch.setenv("NANSEN_WATCH_ADDRESSES", "0xccc, 0xddd")

    settings = Settings(_env_file=None)

    assert settings.debank_watch_addresses == ["0xaaa", "0xbbb"]
    assert settings.nansen_watch_addresses == ["0xccc", "0xddd"]


def test_min_value_thresholds_read_from_env(monkeypatch):
    monkeypatch.setenv("WHALE_ALERT_MIN_VALUE_USD", "1000000")
    monkeypatch.setenv("BITQUERY_MIN_VALUE_USD", "250000")

    settings = Settings(_env_file=None)

    assert settings.whale_alert_min_value_usd == 1_000_000
    assert settings.bitquery_min_value_usd == 250_000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: FAIL — `AttributeError` on the new fields (none exist on `Settings` yet).

- [ ] **Step 3: Write the implementation**

Replace the contents of `src/hello_coin/ingestion/config.py`:

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
    etherscan_api_key: str | None = None
    etherscan_watch_addresses: Annotated[list[str], NoDecode] = []

    debank_access_key: str | None = None
    debank_watch_addresses: Annotated[list[str], NoDecode] = []
    cryptoquant_api_key: str | None = None
    nansen_api_key: str | None = None
    nansen_watch_addresses: Annotated[list[str], NoDecode] = []
    whale_alert_api_key: str | None = None
    whale_alert_min_value_usd: int = 500_000
    bitquery_access_token: str | None = None
    bitquery_min_value_usd: int = 500_000

    @field_validator(
        "hyperliquid_watch_addresses",
        "exchange_watch_symbols",
        "etherscan_watch_addresses",
        "debank_watch_addresses",
        "nansen_watch_addresses",
        mode="before",
    )
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
```

Edit `.env.example`, append:

```
# DeBank Cloud AccessKey (paid, unit-based — register at cloud.debank.com) and comma-separated
# wallet addresses to snapshot total portfolio value for.
DEBANK_ACCESS_KEY=
DEBANK_WATCH_ADDRESSES=

# CryptoQuant API key (docs.cryptoquant.com) for the BTC Exchange Whale Ratio indicator.
CRYPTOQUANT_API_KEY=

# Nansen API key (docs.nansen.ai) and comma-separated wallet addresses to watch for labeled
# on-chain transactions.
NANSEN_API_KEY=
NANSEN_WATCH_ADDRESSES=

# Whale Alert API key (developer.whale-alert.io) and minimum USD value for the global large-
# transaction feed (no watch-address list needed — this is a global feed, not per-wallet).
WHALE_ALERT_API_KEY=
WHALE_ALERT_MIN_VALUE_USD=500000

# Bitquery OAuth access token (account.bitquery.io) and minimum USD value for the global
# large-transfer feed on Ethereum.
BITQUERY_ACCESS_TOKEN=
BITQUERY_MIN_VALUE_USD=500000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/config.py .env.example tests/ingestion/test_config.py
git commit -m "Add settings for DeBank, CryptoQuant, Nansen, Whale Alert, Bitquery"
```

---

### Task 2: CryptoQuant adapter (fully verified)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/cryptoquant.py`
- Test: `tests/ingestion/test_cryptoquant.py`

**Verified live:** `curl "https://api.cryptoquant.com/v1/btc/flow-indicator/exchange-whale-ratio?exchange=binance&window=day&limit=2"`
(no auth) returned
`{"result":{},"status":{"code":401,"message":"unauthorized","description":"401 Unauthorized: Token does not exists. Unable to find token or please use 'Authorization: Bearer API_KEY' header."}}`
with HTTP 401 — confirms the URL, and confirms auth is `Authorization: Bearer <key>`. The
success response schema (`{"status":{"code","message"},"result":{"window","data":[{"date",
"exchange_whale_ratio"}]}}`) is quoted directly from CryptoQuant's own OpenAPI spec at
`docs.cryptoquant.com/openapi/v1.json`.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_cryptoquant.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.cryptoquant import (
    CRYPTOQUANT_WHALE_RATIO_URL,
    CryptoQuantAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

RATIO_RESPONSE = {
    "status": {"code": 200, "message": "success"},
    "result": {
        "window": "day",
        "data": [
            {"date": "2026-08-20", "exchange_whale_ratio": 0.42},
            {"date": "2026-08-21", "exchange_whale_ratio": 0.47},
        ],
    },
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(cryptoquant_api_key=None)
    adapter = CryptoQuantAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_latest_ratio_into_whale_metric():
    respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    metrics = await adapter.fetch()

    assert len(metrics) == 1
    metric = metrics[0]
    assert isinstance(metric, WhaleMetric)
    assert metric.source == "cryptoquant"
    assert metric.symbol == "BTC"
    assert metric.metric_name == "exchange_whale_ratio"
    assert metric.value == 0.47
    assert metric.dedup_key == "BTC:2026-08-21"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_bearer_auth_header():
    route = respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=RATIO_RESPONSE)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_data():
    empty_response = {"status": {"code": 200, "message": "success"}, "result": {"data": []}}
    respx.get(CRYPTOQUANT_WHALE_RATIO_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(cryptoquant_api_key="test-key")
    adapter = CryptoQuantAdapter(settings)

    metrics = await adapter.fetch()

    assert metrics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_cryptoquant.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.cryptoquant'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/cryptoquant.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleMetric

CRYPTOQUANT_WHALE_RATIO_URL = (
    "https://api.cryptoquant.com/v1/btc/flow-indicator/exchange-whale-ratio"
)


def _parse_row(row: dict[str, Any]) -> WhaleMetric:
    date_str = row["date"]
    return WhaleMetric(
        source="cryptoquant",
        timestamp=datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC),
        symbol="BTC",
        metric_name="exchange_whale_ratio",
        value=float(row["exchange_whale_ratio"]),
        dedup_key=f"BTC:{date_str}",
        raw=row,
    )


class CryptoQuantAdapter(Adapter):
    """Polls CryptoQuant's Exchange Whale Ratio indicator for BTC on Binance
    — one of the few indicators available on CryptoQuant's free tier. Needs a
    CryptoQuant API key (Bearer auth).
    """

    name = "cryptoquant"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.cryptoquant_api_key)

    async def fetch(self) -> list[WhaleMetric]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                CRYPTOQUANT_WHALE_RATIO_URL,
                params={"exchange": "binance", "window": "day", "limit": 1},
                headers={"Authorization": f"Bearer {self._settings.cryptoquant_api_key}"},
            )
            response.raise_for_status()
            rows = response.json().get("result", {}).get("data", [])
            if not rows:
                return []
            latest = max(rows, key=lambda row: row["date"])
            return [_parse_row(latest)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_cryptoquant.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/cryptoquant.py tests/ingestion/test_cryptoquant.py
git commit -m "Add CryptoQuant exchange whale ratio adapter"
```

---

### Task 3: DeBank adapter (fully verified)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/debank.py`
- Test: `tests/ingestion/test_debank.py`

**Verified via official docs** (`docs.cloud.debank.com/en/readme/api-pro-reference/user`):
`GET https://pro-openapi.debank.com/v1/user/total_balance?id={address}` with header
`AccessKey: <key>` returns `{"total_usd_value": <float>, "chain_list": [{"id","community_id",
"name","native_token_id","logo_url","wrapped_token_id","usd_value"}]}`. This is a portfolio
*snapshot*, not a discrete transfer — modeled as a `WhaleEvent` with `event_type="position"`
(the same event type Hyperliquid uses for per-wallet position data), `symbol="USD"` (the value
is already aggregated in USD across chains, so there's no single token symbol), and a
timestamp-based `dedup_key` so each poll records a fresh point in the wallet's value-over-time
series (there's no natural "row id" to dedupe on — every poll is a genuinely new data point).

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_debank.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.debank import DEBANK_TOTAL_BALANCE_URL, DebankAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

BALANCE_RESPONSE = {
    "total_usd_value": 27654.142997146177,
    "chain_list": [
        {
            "id": "eth",
            "community_id": 1,
            "name": "Ethereum",
            "native_token_id": "eth",
            "logo_url": "https://static.debank.com/image/chain/logo_url/eth/x.png",
            "wrapped_token_id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "usd_value": 11937.702345945296,
        }
    ],
}


def test_is_configured_true_when_key_and_addresses_set():
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_key():
    settings = Settings(debank_access_key=None, debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[])
    adapter = DebankAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_total_balance_into_position_event():
    respx.get(DEBANK_TOTAL_BALANCE_URL).mock(
        return_value=httpx.Response(200, json=BALANCE_RESPONSE)
    )
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "debank"
    assert event.event_type == "position"
    assert event.side is None
    assert event.symbol == "USD"
    assert event.amount == pytest.approx(27654.142997146177)
    assert event.amount_usd == pytest.approx(27654.142997146177)
    assert event.wallet_address == ADDRESS
    assert event.dedup_key.startswith(f"{ADDRESS}:")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_access_key_header():
    route = respx.get(DEBANK_TOTAL_BALANCE_URL).mock(
        return_value=httpx.Response(200, json=BALANCE_RESPONSE)
    )
    settings = Settings(debank_access_key="test-key", debank_watch_addresses=[ADDRESS])
    adapter = DebankAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["AccessKey"] == "test-key"
    assert route.calls[0].request.url.params["id"] == ADDRESS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_debank.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.debank'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/debank.py`:

```python
from datetime import UTC, datetime

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

DEBANK_TOTAL_BALANCE_URL = "https://pro-openapi.debank.com/v1/user/total_balance"


class DebankAdapter(Adapter):
    """Polls DeBank Cloud for a watched wallet's total portfolio value across
    all chains — a snapshot, recorded as a `position` event. Needs a paid
    DeBank Cloud AccessKey (unit-based billing).
    """

    name = "debank"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.debank_access_key) and bool(
            self._settings.debank_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.debank_watch_addresses:
                response = await client.get(
                    DEBANK_TOTAL_BALANCE_URL,
                    params={"id": address},
                    headers={"AccessKey": self._settings.debank_access_key},
                )
                response.raise_for_status()
                payload = response.json()
                total_usd_value = float(payload["total_usd_value"])
                now = datetime.now(tz=UTC)
                events.append(
                    WhaleEvent(
                        source="debank",
                        timestamp=now,
                        chain_or_exchange="multi-chain",
                        symbol="USD",
                        event_type="position",
                        side=None,
                        amount=total_usd_value,
                        amount_usd=total_usd_value,
                        wallet_address=address,
                        dedup_key=f"{address}:{now.isoformat()}",
                        raw=payload,
                    )
                )
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_debank.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/debank.py tests/ingestion/test_debank.py
git commit -m "Add DeBank total-portfolio-value adapter"
```

---

### Task 4: Nansen adapter (fully verified)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/nansen.py`
- Test: `tests/ingestion/test_nansen.py`

**Verified live:** `POST https://api.nansen.ai/api/v1/profiler/address/transactions` with a
realistic body and no auth returned HTTP 402 with a body whose embedded schema echoes the
documented field names verbatim (`address`, `chain`, `date`, `hide_spam_token`,
`filters.volume_usd.min`, `pagination`) — independently confirms the request shape from
`docs.nansen.ai/api/profiler/address-transactions`. Auth header is `apikey: <key>`.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_nansen.py`:

```python
import json

import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.nansen import NANSEN_TRANSACTIONS_URL, NansenAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

TRANSACTIONS_RESPONSE = {
    "pagination": {"page": 1, "per_page": 100, "total": 1},
    "data": [
        {
            "chain": "ethereum",
            "method": "transfer",
            "tokens_sent": [
                {
                    "token_symbol": "USDC",
                    "token_amount": "150000.0",
                    "price_usd": "1.0",
                    "value_usd": "150000.0",
                    "token_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "chain": "ethereum",
                    "from_address": ADDRESS,
                    "to_address": "0x2222222222222222222222222222222222222222",
                    "from_address_label": "Whale Wallet",
                    "to_address_label": None,
                }
            ],
            "tokens_received": [],
            "volume_usd": "150000.0",
            "block_timestamp": "2026-08-21T12:00:00Z",
            "transaction_hash": "0xabc123",
            "source_type": "dex",
        }
    ],
}


def test_is_configured_true_when_key_and_addresses_set():
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_key():
    settings = Settings(nansen_api_key=None, nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[])
    adapter = NansenAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transaction_into_whale_event():
    respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "nansen"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "USDC"
    assert event.event_type == "transfer"
    assert event.side == "sell"
    assert event.amount == 150000.0
    assert event.amount_usd == 150000.0
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xabc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_apikey_header_and_documented_body_fields():
    route = respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    await adapter.fetch()

    request = route.calls[0].request
    assert request.headers["apikey"] == "test-key"
    body = json.loads(request.content)
    assert body["address"] == ADDRESS
    assert body["chain"] == "ethereum"
    assert "date" in body


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_transactions():
    empty_response = {"pagination": {"page": 1, "per_page": 100, "total": 0}, "data": []}
    respx.post(NANSEN_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    settings = Settings(nansen_api_key="test-key", nansen_watch_addresses=[ADDRESS])
    adapter = NansenAdapter(settings)

    events = await adapter.fetch()

    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_nansen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.nansen'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/nansen.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

NANSEN_TRANSACTIONS_URL = "https://api.nansen.ai/api/v1/profiler/address/transactions"


def _parse_transaction(address: str, row: dict[str, Any]) -> WhaleEvent | None:
    tokens_sent = row.get("tokens_sent") or []
    tokens_received = row.get("tokens_received") or []
    if tokens_sent:
        token, side = tokens_sent[0], "sell"
    elif tokens_received:
        token, side = tokens_received[0], "buy"
    else:
        return None
    return WhaleEvent(
        source="nansen",
        timestamp=datetime.fromisoformat(row["block_timestamp"].replace("Z", "+00:00")),
        chain_or_exchange=row["chain"],
        symbol=token["token_symbol"],
        event_type="transfer",
        side=side,
        amount=float(token["token_amount"]),
        amount_usd=float(row["volume_usd"]) if row.get("volume_usd") is not None else None,
        wallet_address=address,
        dedup_key=row["transaction_hash"],
        raw=row,
    )


class NansenAdapter(Adapter):
    """Watches a configured list of wallet addresses for labeled on-chain
    transactions via Nansen's Address Transactions endpoint. Needs a paid
    Nansen API key.
    """

    name = "nansen"
    poll_interval_seconds = 300

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen: dict[str, datetime] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.nansen_api_key) and bool(
            self._settings.nansen_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        now = datetime.now(tz=UTC)
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.nansen_watch_addresses:
                start = self._last_seen.get(address, now - timedelta(hours=1))
                response = await client.post(
                    NANSEN_TRANSACTIONS_URL,
                    headers={"apikey": self._settings.nansen_api_key},
                    json={
                        "address": address,
                        "chain": "ethereum",
                        "date": {"from": start.isoformat(), "to": now.isoformat()},
                    },
                )
                response.raise_for_status()
                rows = response.json().get("data", [])
                for row in rows:
                    event = _parse_transaction(address, row)
                    if event is not None:
                        events.append(event)
                self._last_seen[address] = now
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_nansen.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/nansen.py tests/ingestion/test_nansen.py
git commit -m "Add Nansen labeled-transaction adapter"
```

---

### Task 5: Whale Alert adapter (request verified live; response schema lower-confidence)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/whale_alert.py`
- Test: `tests/ingestion/test_whale_alert.py`

**Verified live:** `curl "https://api.whale-alert.io/v1/transactions"` (no key) →
`{"result":"error","message":"required parameter: api_key"}`; with a bogus key →
`{"result":"error","message":"invalid api_key"}`. Both are structured, parameter-aware JSON
errors, confirming `https://api.whale-alert.io/v1/transactions` and `api_key` query-param auth
are correct. **Response field names below are secondhand** (search-engine synthesis of the docs,
not a directly fetched first-party JSON sample — the docs page is JS-rendered) — this adapter
therefore parses every field defensively (`.get(...)`, never a bare index) so an unexpected real
shape degrades to a skipped row (logged via the base `Adapter`'s failure handling) rather than a
hard crash. **Validate against a real key before trusting this adapter's output.**

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_whale_alert.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.whale_alert import (
    WHALE_ALERT_TRANSACTIONS_URL,
    WhaleAlertAdapter,
)
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

TRANSACTIONS_RESPONSE = {
    "result": "success",
    "cursor": "abc",
    "count": 1,
    "transactions": [
        {
            "blockchain": "ethereum",
            "symbol": "usdt",
            "id": 123456,
            "transaction_type": "transfer",
            "hash": "0xabc123",
            "from": {"address": "0x1111111111111111111111111111111111111111", "owner": "binance"},
            "to": {"address": "0x2222222222222222222222222222222222222222", "owner": "unknown"},
            "timestamp": 1787372700,
            "amount": 5_000_000.0,
            "amount_usd": 5_000_000.0,
            "transaction_count": 1,
        }
    ],
}


def test_is_configured_true_when_api_key_set():
    settings = Settings(whale_alert_api_key="test-key")
    adapter = WhaleAlertAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_api_key():
    settings = Settings(whale_alert_api_key=None)
    adapter = WhaleAlertAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transaction_into_whale_event():
    respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(whale_alert_api_key="test-key", whale_alert_min_value_usd=500_000)
    adapter = WhaleAlertAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "whale_alert"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "usdt"
    assert event.event_type == "transfer"
    assert event.amount == 5_000_000.0
    assert event.amount_usd == 5_000_000.0
    assert event.wallet_address == "0x2222222222222222222222222222222222222222"
    assert event.dedup_key == "0xabc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_api_key_and_min_value_params():
    route = respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=TRANSACTIONS_RESPONSE)
    )
    settings = Settings(whale_alert_api_key="test-key", whale_alert_min_value_usd=1_000_000)
    adapter = WhaleAlertAdapter(settings)

    await adapter.fetch()

    params = route.calls[0].request.url.params
    assert params["api_key"] == "test-key"
    assert params["min_value"] == "1000000"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_skips_transactions_missing_expected_fields():
    malformed_response = {
        "result": "success",
        "cursor": "abc",
        "count": 1,
        "transactions": [{"blockchain": "ethereum", "symbol": "usdt"}],
    }
    respx.get(WHALE_ALERT_TRANSACTIONS_URL).mock(
        return_value=httpx.Response(200, json=malformed_response)
    )
    settings = Settings(whale_alert_api_key="test-key")
    adapter = WhaleAlertAdapter(settings)

    events = await adapter.fetch()

    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_whale_alert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.whale_alert'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/whale_alert.py`:

```python
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

WHALE_ALERT_TRANSACTIONS_URL = "https://api.whale-alert.io/v1/transactions"
ONE_HOUR_SECONDS = 3600


def _parse_transaction(row: dict[str, Any]) -> WhaleEvent | None:
    """Field names here are the best-documented shape found (see the plan's
    'Verified live' note) but are NOT first-party-confirmed — every access is
    defensive so a shape mismatch skips this row instead of raising."""
    tx_hash = row.get("hash")
    timestamp = row.get("timestamp")
    amount = row.get("amount")
    if tx_hash is None or timestamp is None or amount is None:
        return None
    to_address = (row.get("to") or {}).get("address")
    return WhaleEvent(
        source="whale_alert",
        timestamp=datetime.fromtimestamp(int(timestamp), tz=UTC),
        chain_or_exchange=row.get("blockchain", "unknown"),
        symbol=row.get("symbol", "unknown"),
        event_type="transfer",
        side=None,
        amount=float(amount),
        amount_usd=float(row["amount_usd"]) if row.get("amount_usd") is not None else None,
        wallet_address=to_address,
        dedup_key=tx_hash,
        raw=row,
    )


class WhaleAlertAdapter(Adapter):
    """Polls Whale Alert's global large-transaction feed (no watch-address
    list needed — every chain, filtered by `min_value`). Needs a paid Whale
    Alert API key. See the plan's confidence note: response field names are
    secondhand, parsed defensively.
    """

    name = "whale_alert"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._last_seen_ts = int(time.time()) - ONE_HOUR_SECONDS

    def is_configured(self) -> bool:
        return bool(self._settings.whale_alert_api_key)

    async def fetch(self) -> list[WhaleEvent]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                WHALE_ALERT_TRANSACTIONS_URL,
                params={
                    "api_key": self._settings.whale_alert_api_key,
                    "start": self._last_seen_ts,
                    "min_value": self._settings.whale_alert_min_value_usd,
                },
            )
            response.raise_for_status()
            rows = response.json().get("transactions", [])
            events = [event for row in rows if (event := _parse_transaction(row)) is not None]
            timestamps = [row["timestamp"] for row in rows if row.get("timestamp") is not None]
            if timestamps:
                self._last_seen_ts = max(timestamps) + 1
            return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_whale_alert.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/whale_alert.py tests/ingestion/test_whale_alert.py
git commit -m "Add Whale Alert global large-transaction adapter"
```

---

### Task 6: Bitquery adapter (request verified live; query shape lower-confidence)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/bitquery.py`
- Test: `tests/ingestion/test_bitquery.py`

**Verified live:** `curl -X POST "https://streaming.bitquery.io/graphql" -d '{"query":"{ __typename }"}'`
(no auth) → `Unauthorized. Provide Authorization as documented at
https://docs.bitquery.io/docs/category/authorization` — confirms the endpoint and that auth is
`Authorization: Bearer <token>`. **The GraphQL query field set below is well-sourced (directly
quoted from `docs.bitquery.io/docs/schema/evm/transfers/`) but the top-level query wrapper was
not independently re-verified against a live 200 response** (GraphQL auth errors are plain text,
not structured, so a live check can't confirm field names the way the other adapters' JSON
errors did). This adapter raises a clear `RuntimeError` on any `errors` key in the GraphQL
response (a normal, documented GraphQL behavior for a bad query), so a wrong field name fails
loudly via the base `Adapter`'s retry/disable logic rather than silently returning nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_bitquery.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.bitquery import BITQUERY_GRAPHQL_URL, BitqueryAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

TRANSFERS_RESPONSE = {
    "data": {
        "EVM": {
            "Transfers": [
                {
                    "Transfer": {
                        "Amount": "12.5",
                        "AmountInUSD": "875000.0",
                        "Currency": {
                            "Fungible": True,
                            "Name": "Wrapped Ether",
                            "ProtocolName": None,
                            "Symbol": "WETH",
                        },
                        "Sender": "0x1111111111111111111111111111111111111111",
                        "Receiver": "0x2222222222222222222222222222222222222222",
                        "Success": True,
                        "Type": "transfer",
                        "Id": "abc123",
                    }
                }
            ]
        }
    }
}

ERROR_RESPONSE = {"errors": [{"message": "Field 'Bogus' doesn't exist on type 'Transfer_Set'"}]}


def test_is_configured_true_when_token_set():
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)
    assert adapter.is_configured() is True


def test_is_configured_false_when_no_token():
    settings = Settings(bitquery_access_token=None)
    adapter = BitqueryAdapter(settings)
    assert adapter.is_configured() is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_transfer_into_whale_event():
    respx.post(BITQUERY_GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=TRANSFERS_RESPONSE)
    )
    settings = Settings(bitquery_access_token="test-token", bitquery_min_value_usd=500_000)
    adapter = BitqueryAdapter(settings)

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "bitquery"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "WETH"
    assert event.event_type == "transfer"
    assert event.amount == 12.5
    assert event.amount_usd == 875000.0
    assert event.wallet_address == "0x2222222222222222222222222222222222222222"
    assert event.dedup_key == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sends_bearer_auth_header():
    route = respx.post(BITQUERY_GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json=TRANSFERS_RESPONSE)
    )
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)

    await adapter.fetch()

    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_graphql_error():
    respx.post(BITQUERY_GRAPHQL_URL).mock(return_value=httpx.Response(200, json=ERROR_RESPONSE))
    settings = Settings(bitquery_access_token="test-token")
    adapter = BitqueryAdapter(settings)

    with pytest.raises(RuntimeError, match="Bogus"):
        await adapter.fetch()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_bitquery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.bitquery'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/bitquery.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

BITQUERY_GRAPHQL_URL = "https://streaming.bitquery.io/graphql"

_TRANSFERS_QUERY = """
{
  EVM(network: eth, dataset: combined) {
    Transfers(limit: {count: 20}, orderBy: {descending: Block_Time},
               where: {Transfer: {AmountInUSD: {ge: "%(min_value)s"}}}) {
      Transfer {
        Amount
        AmountInUSD
        Currency { Fungible Name ProtocolName Symbol }
        Sender
        Receiver
        Success
        Type
        Id
      }
    }
  }
}
"""


def _parse_transfer(row: dict[str, Any]) -> WhaleEvent:
    transfer = row["Transfer"]
    return WhaleEvent(
        source="bitquery",
        timestamp=datetime.now(tz=UTC),
        chain_or_exchange="ethereum",
        symbol=transfer["Currency"]["Symbol"],
        event_type="transfer",
        side=None,
        amount=float(transfer["Amount"]),
        amount_usd=float(transfer["AmountInUSD"]) if transfer.get("AmountInUSD") else None,
        wallet_address=transfer["Receiver"],
        dedup_key=transfer["Id"],
        raw=transfer,
    )


class BitqueryAdapter(Adapter):
    """Polls Bitquery's GraphQL API for large Ethereum transfers above
    `bitquery_min_value_usd`. Needs a Bitquery OAuth access token. See the
    plan's confidence note: query field set is well-sourced but not
    independently re-verified against a live 200 response.
    """

    name = "bitquery"
    poll_interval_seconds = 60

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.bitquery_access_token)

    async def fetch(self) -> list[WhaleEvent]:
        query = _TRANSFERS_QUERY % {"min_value": self._settings.bitquery_min_value_usd}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                BITQUERY_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {self._settings.bitquery_access_token}"},
                json={"query": query},
            )
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise RuntimeError(f"Bitquery GraphQL error: {payload['errors']}")
            rows = payload.get("data", {}).get("EVM", {}).get("Transfers", [])
            return [_parse_transfer(row) for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_bitquery.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/bitquery.py tests/ingestion/test_bitquery.py
git commit -m "Add Bitquery large-transfer adapter"
```

---

### Task 7: Wire all five into the registry

**Files:**
- Modify: `src/hello_coin/ingestion/registry.py`
- Modify: `tests/ingestion/test_registry.py`

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/ingestion/test_registry.py`:

```python
import logging

from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters

ALL_NAMES = [
    "hyperliquid",
    "binance",
    "okx",
    "bybit",
    "bitget",
    "etherscan_ethereum",
    "etherscan_bsc",
    "etherscan_polygon",
    "cryptoquant",
    "debank",
    "nansen",
    "whale_alert",
    "bitquery",
]


def test_build_adapters_includes_all_configured_sources():
    settings = Settings(
        hyperliquid_watch_addresses=["0xabc"],
        etherscan_api_key="test-key",
        etherscan_watch_addresses=["0xabc"],
        cryptoquant_api_key="test-key",
        debank_access_key="test-key",
        debank_watch_addresses=["0xabc"],
        nansen_api_key="test-key",
        nansen_watch_addresses=["0xabc"],
        whale_alert_api_key="test-key",
        bitquery_access_token="test-token",
    )

    adapters = build_adapters(settings)

    assert [a.name for a in adapters] == ALL_NAMES


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


def test_build_adapters_skips_etherscan_chains_when_not_configured(caplog):
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    assert "etherscan_ethereum" not in [a.name for a in adapters]
    for chain in ("etherscan_ethereum", "etherscan_bsc", "etherscan_polygon"):
        assert chain in caplog.text


def test_build_adapters_skips_freemium_sources_when_not_configured(caplog):
    settings = Settings(hyperliquid_watch_addresses=["0xabc"])

    with caplog.at_level(logging.WARNING):
        adapters = build_adapters(settings)

    names = [a.name for a in adapters]
    for source in ("cryptoquant", "debank", "nansen", "whale_alert", "bitquery"):
        assert source not in names
        assert source in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: FAIL — `test_build_adapters_includes_all_configured_sources` fails because
`build_adapters` doesn't include the five new entries yet.

- [ ] **Step 3: Write the implementation**

Replace the contents of `src/hello_coin/ingestion/registry.py`:

```python
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bitquery import BitqueryAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.cryptoquant import CryptoQuantAdapter
from hello_coin.ingestion.adapters.debank import DebankAdapter
from hello_coin.ingestion.adapters.etherscan import ETHERSCAN_CHAINS, EtherscanAdapter
from hello_coin.ingestion.adapters.hyperliquid import HyperliquidAdapter
from hello_coin.ingestion.adapters.nansen import NansenAdapter
from hello_coin.ingestion.adapters.okx import OkxAdapter
from hello_coin.ingestion.adapters.whale_alert import WhaleAlertAdapter
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
        *(EtherscanAdapter(settings, chain_key=chain_key) for chain_key in ETHERSCAN_CHAINS),
        CryptoQuantAdapter(settings),
        DebankAdapter(settings),
        NansenAdapter(settings),
        WhaleAlertAdapter(settings),
        BitqueryAdapter(settings),
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
Expected: `5 passed`

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/registry.py tests/ingestion/test_registry.py
git commit -m "Wire CryptoQuant/DeBank/Nansen/Whale Alert/Bitquery into the registry"
```

---

### Task 8: Update the design spec and docs

**Files:**
- Modify: `docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update the spec's file tree**

In `docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md`, in the file-tree code
block, add a one-line comment after each of `debank.py`, `whale_alert.py`, `bitquery.py`,
`nansen.py`, `cryptoquant.py` noting they're implemented, e.g.:

```
      debank.py        # DeBank Cloud (paid, unit-based) — implemented
      whale_alert.py   # global feed, min_value filter — implemented, response schema
                       # secondhand-sourced (see 2026-08-22-freemium-paid-adapters.md)
      bitquery.py      # GraphQL, global feed — implemented, query shape not 100%
                       # verbatim-confirmed (see 2026-08-22-freemium-paid-adapters.md)
      nansen.py        # per-wallet labeled transactions — implemented, fully verified
      arkham.py        # DEFERRED — HMAC signing scheme undocumented, not implemented
      cryptoquant.py   # exchange whale ratio — implemented, fully verified
```

Add a `solscan.py` line next to the existing `etherscan.py`/`solscan.py` lines noting it's
still deferred (paid-only, endpoint schema unverified):

```
      solscan.py       # DEFERRED — paid-only ($49/mo min), response schema unverified
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, in the `## Architecture` section, replace:

```
- `adapters/*.py` — one file per data source: `hyperliquid.py` (per-wallet fills),
  `binance.py`/`okx.py`/`bybit.py`/`bitget.py` (public long/short account-ratio metrics, no API
  key needed), and `etherscan.py` (per-wallet transfers on Ethereum/BSC/Polygon via Etherscan's
  unified V2 API — one class, three registered instances, one per `chainid`; needs a free
  Etherscan API key).
```

with:

```
- `adapters/*.py` — one file per data source:
  - No key needed: `hyperliquid.py`, `binance.py`, `okx.py`, `bybit.py`, `bitget.py`.
  - Free key: `etherscan.py` (Ethereum/BSC/Polygon via Etherscan's unified V2 API — one class,
    three registered instances, one per `chainid`).
  - Paid/freemium key: `cryptoquant.py`, `debank.py`, `nansen.py`, `whale_alert.py`,
    `bitquery.py`. None of these have been smoke-tested against a real key — see
    `docs/superpowers/plans/2026-08-22-freemium-paid-adapters.md` for per-adapter confidence
    notes (Whale Alert and Bitquery parse their responses defensively since their exact
    response shape wasn't first-party-confirmed).
  - Deferred (not implemented — insufficient verification): ClankApp, Solscan, Arkham. See the
    same plan doc for why.
```

- [ ] **Step 3: Update README.md**

In `README.md`, in the `## Whale ingestion` section, add after the Etherscan bullet:

```markdown
3. The paid/freemium adapters (CryptoQuant, DeBank, Nansen, Whale Alert, Bitquery) each need
   their own key in `.env` — see `.env.example` for the exact variable names. None of these
   have been verified against a real key in this environment; if a response shape turns out to
   differ from what's implemented, that adapter will show repeated failures in the logs and
   disable itself after a few consecutive misses (see `Adapter.safe_fetch` in
   `src/hello_coin/ingestion/adapters/base.py`) rather than crash the service.
```

Renumber the remaining list items to stay sequential.

- [ ] **Step 4: Run the full test suite and lint one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-22-whale-data-ingestion-design.md CLAUDE.md README.md
git commit -m "Document the freemium/paid adapters and deferred sources"
```
