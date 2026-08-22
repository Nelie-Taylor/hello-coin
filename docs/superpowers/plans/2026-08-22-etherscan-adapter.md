# Etherscan-Family Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a whale-event adapter that watches a configured list of EVM wallet addresses for
normal-transaction transfers on Ethereum, BNB Smart Chain, and Polygon, using Etherscan's unified
V2 API (one API key, `chainid` selects the chain).

**Architecture:** Same adapter pattern as the other adapters. Unlike Hyperliquid (fully public) or
the exchange derivatives adapters (also fully public), Etherscan's API now **requires a free API
key** — confirmed live: a request without `apikey` returns
`{"status":"0","message":"NOTOK","result":"Missing/Invalid API Key"}`. This is one adapter class
(`EtherscanAdapter`) instantiated three times — once per chain — sharing the same watch-address
list and API key, since Etherscan's V2 API is genuinely one endpoint parametrized by `chainid`
(confirmed live via `curl` and via `docs.etherscan.io/api-reference/endpoint/txlist.md`).
**Solana/Solscan is explicitly out of scope for this plan** — Solana is not an EVM chain and is
not covered by Etherscan's V2 API (confirmed via `docs.etherscan.io/supported-chains.md`); it
needs its own adapter in a future plan.

**Scope note — sources dropped from this batch:** The original free-key group also included
ClankApp and DeBank. Both were re-researched while writing this plan and no longer fit a
"free, verifiable" adapter:
- **ClankApp**: `clankapp.com` is behind a Cloudflare bot challenge (blocks automated fetches),
  and the `api.clankapp.com` / `docs.clankapp.com` subdomains a web search suggested do not
  resolve in DNS. There's no way to verify a real endpoint shape right now — writing adapter code
  against unverified, possibly-hallucinated endpoint details would violate this project's
  no-guessed-code standard. Deferred until this can be verified (e.g. the user registering and
  sharing real docs/response samples).
- **DeBank**: the free "Open API" described in earlier research has been superseded by "DeBank
  Cloud" — confirmed via `docs.cloud.debank.com`: getting an `AccessKey` requires registering,
  and usage is unit-based/paid (Pro Plan pricing, units purchased via dashboard). This moves
  DeBank from the free-key group into the same freemium/paid bucket as Whale Alert, Bitquery,
  Nansen, Arkham, and CryptoQuant, to be planned alongside those later.

**Tech Stack:** Same as prior adapters — `httpx`, `pydantic-settings`, `pytest` +
`pytest-asyncio` + `respx`.

---

### Task 1: Etherscan settings

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `.env.example`
- Modify: `tests/ingestion/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_config.py`:

```python
def test_etherscan_api_key_defaults_to_none(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.etherscan_api_key is None


def test_etherscan_watch_addresses_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_WATCH_ADDRESSES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.etherscan_watch_addresses == []


def test_etherscan_watch_addresses_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("ETHERSCAN_WATCH_ADDRESSES", "0xaaa, 0xbbb ,0xccc")

    settings = Settings(_env_file=None)

    assert settings.etherscan_watch_addresses == ["0xaaa", "0xbbb", "0xccc"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: FAIL — `AttributeError` on the three new tests (no `etherscan_api_key` /
`etherscan_watch_addresses` attributes yet).

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

    @field_validator(
        "hyperliquid_watch_addresses",
        "exchange_watch_symbols",
        "etherscan_watch_addresses",
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
# Free Etherscan API key (register at etherscan.io) and comma-separated EVM wallet addresses
# to watch for transfers on Ethereum, BSC, and Polygon (Etherscan's unified V2 API).
ETHERSCAN_API_KEY=
ETHERSCAN_WATCH_ADDRESSES=
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/config.py .env.example tests/ingestion/test_config.py
git commit -m "Add Etherscan API key and watch-address settings"
```

---

### Task 2: Etherscan adapter (parametrized per chain)

**Files:**
- Create: `src/hello_coin/ingestion/adapters/etherscan.py`
- Test: `tests/ingestion/test_etherscan.py`

**Verified live:**
- No API key → `curl "https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist&address=0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604&startblock=0&endblock=99999999&page=1&offset=2&sort=desc"`
  returned `{"status":"0","message":"NOTOK","result":"Missing/Invalid API Key"}` — confirms a key
  is required, and confirms the error shape: `result` is a **string** for real API errors.
- Per `docs.etherscan.io/api-reference/endpoint/txlist.md`, a successful response looks like
  `{"status":"1","message":"OK","result":[{...tx fields...}]}`, and Etherscan's documented
  "no transactions found for this address" case returns `result` as an **empty list**, not a
  string — this adapter uses that distinction (`isinstance(result, str)`) to tell a real API
  error apart from "nothing to report" without guessing at undocumented behavior.
- Chain IDs confirmed via `docs.etherscan.io/supported-chains.md`: Ethereum = 1, BSC = 56,
  Polygon = 137.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_etherscan.py`:

```python
import httpx
import pytest
import respx

from hello_coin.ingestion.adapters.etherscan import ETHERSCAN_V2_API_URL, EtherscanAdapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA9604"

SUCCESS_RESPONSE = {
    "status": "1",
    "message": "OK",
    "result": [
        {
            "blockNumber": "23467053",
            "timeStamp": "1759129619",
            "hash": "0xf9db905d77704596d3600816bc70201586cfeec13bcf576320e2f38d6ca851a",
            "from": "0x2449ecef5012f0a0e153b278ef4fcc9625bc4c78",
            "to": ADDRESS,
            "value": "2500000000000000000",
            "isError": "0",
        },
        {
            "blockNumber": "23467054",
            "timeStamp": "1759129700",
            "hash": "0xdeadbeef00000000000000000000000000000000000000000000000000000",
            "from": "0x1111111111111111111111111111111111111111",
            "to": ADDRESS,
            "value": "1000000000000000000",
            "isError": "1",
        },
    ],
}

NO_TX_RESPONSE = {"status": "0", "message": "No transactions found", "result": []}

ERROR_RESPONSE = {"status": "0", "message": "NOTOK", "result": "Missing/Invalid API Key"}


def _settings(**overrides):
    defaults = {"etherscan_api_key": "test-key", "etherscan_watch_addresses": [ADDRESS]}
    defaults.update(overrides)
    return Settings(**defaults)


def test_is_configured_false_when_no_api_key():
    settings = _settings(etherscan_api_key=None)
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is False


def test_is_configured_false_when_no_addresses():
    settings = _settings(etherscan_watch_addresses=[])
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is False


def test_is_configured_true_when_both_set():
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")
    assert adapter.is_configured() is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_successful_tx_and_skips_failed_one():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=SUCCESS_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    events = await adapter.fetch()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, WhaleEvent)
    assert event.source == "etherscan_ethereum"
    assert event.chain_or_exchange == "ethereum"
    assert event.symbol == "ETH"
    assert event.event_type == "transfer"
    assert event.side is None
    assert event.amount == 2.5
    assert event.wallet_address == ADDRESS
    assert event.dedup_key == "0xf9db905d77704596d3600816bc70201586cfeec13bcf576320e2f38d6ca851a"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_uses_correct_chain_id_and_symbol_for_bsc():
    route = respx.get(ETHERSCAN_V2_API_URL).mock(
        return_value=httpx.Response(200, json=SUCCESS_RESPONSE)
    )
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="bsc")

    events = await adapter.fetch()

    assert route.calls[0].request.url.params["chainid"] == "56"
    assert events[0].source == "etherscan_bsc"
    assert events[0].chain_or_exchange == "bsc"
    assert events[0].symbol == "BNB"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_empty_list_when_no_transactions_found():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=NO_TX_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    events = await adapter.fetch()

    assert events == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_real_api_error():
    respx.get(ETHERSCAN_V2_API_URL).mock(return_value=httpx.Response(200, json=ERROR_RESPONSE))
    settings = _settings()
    adapter = EtherscanAdapter(settings, chain_key="ethereum")

    with pytest.raises(RuntimeError, match="Missing/Invalid API Key"):
        await adapter.fetch()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_etherscan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.ingestion.adapters.etherscan'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/ingestion/adapters/etherscan.py`:

```python
from datetime import UTC, datetime
from typing import Any

import httpx

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.models import WhaleEvent

ETHERSCAN_V2_API_URL = "https://api.etherscan.io/v2/api"

ETHERSCAN_CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {"chain_id": 1, "symbol": "ETH"},
    "bsc": {"chain_id": 56, "symbol": "BNB"},
    "polygon": {"chain_id": 137, "symbol": "MATIC"},
}


def _parse_tx(chain_key: str, symbol: str, address: str, row: dict[str, Any]) -> WhaleEvent:
    return WhaleEvent(
        source=f"etherscan_{chain_key}",
        timestamp=datetime.fromtimestamp(int(row["timeStamp"]), tz=UTC),
        chain_or_exchange=chain_key,
        symbol=symbol,
        event_type="transfer",
        side=None,
        amount=int(row["value"]) / 1e18,
        amount_usd=None,
        wallet_address=address,
        dedup_key=row["hash"],
        raw=row,
    )


class EtherscanAdapter(Adapter):
    """Watches a configured list of EVM wallet addresses for normal-transaction
    transfers, via Etherscan's unified V2 API. One instance per chain
    (`chain_key` selects `chainid`); all instances share the same API key and
    watch-address list. Requires a free Etherscan API key.
    """

    poll_interval_seconds = 60

    def __init__(self, settings: Settings, chain_key: str) -> None:
        super().__init__()
        self._settings = settings
        self._chain_key = chain_key
        self._chain_id = ETHERSCAN_CHAINS[chain_key]["chain_id"]
        self._symbol = ETHERSCAN_CHAINS[chain_key]["symbol"]
        self.name = f"etherscan_{chain_key}"
        self._last_seen_block: dict[str, int] = {}

    def is_configured(self) -> bool:
        return bool(self._settings.etherscan_api_key) and bool(
            self._settings.etherscan_watch_addresses
        )

    async def fetch(self) -> list[WhaleEvent]:
        events: list[WhaleEvent] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for address in self._settings.etherscan_watch_addresses:
                start_block = self._last_seen_block.get(address, 0)
                response = await client.get(
                    ETHERSCAN_V2_API_URL,
                    params={
                        "chainid": self._chain_id,
                        "module": "account",
                        "action": "txlist",
                        "address": address,
                        "startblock": start_block,
                        "endblock": 99999999,
                        "page": 1,
                        "offset": 100,
                        "sort": "asc",
                        "apikey": self._settings.etherscan_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result")
                if payload.get("status") == "0":
                    if isinstance(result, str):
                        raise RuntimeError(
                            f"Etherscan API error for chain {self._chain_id}: {result}"
                        )
                    continue
                rows = result or []
                for row in rows:
                    if row.get("isError") == "0":
                        events.append(_parse_tx(self._chain_key, self._symbol, address, row))
                if rows:
                    self._last_seen_block[address] = max(
                        int(row["blockNumber"]) for row in rows
                    ) + 1
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ingestion/test_etherscan.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/ingestion/adapters/etherscan.py tests/ingestion/test_etherscan.py
git commit -m "Add Etherscan-family whale-transfer adapter (Ethereum/BSC/Polygon)"
```

---

### Task 3: Wire the three chain instances into the registry

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
]


def test_build_adapters_includes_all_configured_sources():
    settings = Settings(
        hyperliquid_watch_addresses=["0xabc"],
        etherscan_api_key="test-key",
        etherscan_watch_addresses=["0xabc"],
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingestion/test_registry.py -v`
Expected: FAIL — `test_build_adapters_includes_all_configured_sources` fails because
`build_adapters` doesn't include the three `etherscan_*` entries yet.

- [ ] **Step 3: Write the implementation**

Replace the contents of `src/hello_coin/ingestion/registry.py`:

```python
import logging

from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.adapters.binance import BinanceAdapter
from hello_coin.ingestion.adapters.bitget import BitgetAdapter
from hello_coin.ingestion.adapters.bybit import BybitAdapter
from hello_coin.ingestion.adapters.etherscan import ETHERSCAN_CHAINS, EtherscanAdapter
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
        *(EtherscanAdapter(settings, chain_key=chain_key) for chain_key in ETHERSCAN_CHAINS),
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
Expected: `4 passed`

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/registry.py tests/ingestion/test_registry.py
git commit -m "Wire Etherscan-family chain adapters into the registry"
```

---

### Task 4: Docs and manual verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

Per the design spec's Testing section, automated real-network smoke tests are limited to
no-auth endpoints (Hyperliquid, Binance, etc. — already covered). Etherscan requires a personal
API key, so this task adds a documented **manual** verification step instead of an automated
`@pytest.mark.network` test (there is no key available to run one in this environment or in CI).

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, in the `## Architecture` section, replace:

```
- `adapters/*.py` — one file per data source: `hyperliquid.py` (per-wallet fills), and
  `binance.py`/`okx.py`/`bybit.py`/`bitget.py` (public long/short account-ratio metrics, no API
  key needed).
```

with:

```
- `adapters/*.py` — one file per data source: `hyperliquid.py` (per-wallet fills),
  `binance.py`/`okx.py`/`bybit.py`/`bitget.py` (public long/short account-ratio metrics, no API
  key needed), and `etherscan.py` (per-wallet transfers on Ethereum/BSC/Polygon via Etherscan's
  unified V2 API — one class, three registered instances, one per `chainid`; needs a free
  Etherscan API key).
```

- [ ] **Step 2: Update README.md**

In `README.md`, in the `## Whale ingestion` section, replace:

```markdown
1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
   `EXCHANGE_WATCH_SYMBOLS` defaults to `BTCUSDT` and needs no key — the Binance/OKX/Bybit/Bitget
   adapters work out of the box.
2. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
   (or `binance`, `okx`, `bybit`, `bitget`).
3. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.
```

with:

```markdown
1. Copy `.env.example` to `.env` and set `HYPERLIQUID_WATCH_ADDRESSES` to one or more
   comma-separated wallet addresses (find some on the Hyperliquid app's public leaderboard).
   `EXCHANGE_WATCH_SYMBOLS` defaults to `BTCUSDT` and needs no key — the Binance/OKX/Bybit/Bitget
   adapters work out of the box.
2. For the Etherscan-family adapters, register a free API key at
   [etherscan.io](https://etherscan.io/apis) and set `ETHERSCAN_API_KEY` plus
   `ETHERSCAN_WATCH_ADDRESSES` (comma-separated EVM wallet addresses) in `.env`. These adapters
   watch Ethereum, BSC, and Polygon with the same key/address list.
3. Fetch once from a single adapter to sanity-check it: `uv run hello-coin ingest test hyperliquid`
   (or `binance`, `okx`, `bybit`, `bitget`, `etherscan_ethereum`, `etherscan_bsc`,
   `etherscan_polygon`).
4. Run the service continuously: `uv run hello-coin ingest run` — writes to `data/whale.db`.
```

- [ ] **Step 3: Manually verify against the real Etherscan API**

This step needs a real, free Etherscan API key — not run automatically:

1. Register at https://etherscan.io/apis and copy the API key.
2. In `.env`, set `ETHERSCAN_API_KEY=<your key>` and `ETHERSCAN_WATCH_ADDRESSES=` to a known
   active wallet address (e.g. an exchange hot wallet from https://etherscan.io/accounts).
3. Run: `uv run hello-coin ingest test etherscan_ethereum`
   Expected: either prints `WhaleEvent(...)` lines for recent transfers, or nothing if that
   address has no transfers in its transaction history window (try a different, more active
   address if so).
4. Repeat for `etherscan_bsc` and `etherscan_polygon` with an address active on those chains.

- [ ] **Step 4: Run the full test suite one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the Etherscan-family adapter"
```
