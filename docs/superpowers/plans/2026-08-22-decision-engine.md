# Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/hello_coin/decision/` so `uv run hello-coin decision run` computes a whale
score (from `data/whale.db`) and a technical score (from `data/technical.db`) per watched
symbol, calls the Anthropic API for a structured buy/sell/hold decision, and stores it in
`data/decisions.db` — closing the loop described in `docs/superpowers/specs/2026-08-22-decision-engine-design.md`.

**Verified against the real `anthropic` SDK before writing this plan** (not guessed): added
`anthropic` as a dependency and inspected the installed package directly —
`AsyncAnthropic.__init__`, `AsyncMessages.create`'s parameters (`model`, `max_tokens`,
`messages`, `system`, `tools`, `tool_choice`), `ToolParam`'s fields (`name`, `description`,
`input_schema`), `ToolChoiceToolParam`'s fields (`type: "tool"`, `name`), `ToolUseBlock`'s
fields (`type: "tool_use"`, `name`, `input: dict`), and confirmed `"claude-sonnet-5"` is a
literal value in the SDK's own `ModelParam` type. `ToolParam`/`ToolChoiceToolParam` are
`TypedDict`s (confirmed via `typing_extensions._TypedDictMeta`), so plain Python dicts are the
correct runtime values — no need to construct SDK model instances. `AsyncAnthropic` supports
`async with` (confirmed `__aenter__`/`__aexit__` exist), matching this codebase's existing
`async with httpx.AsyncClient(...)` pattern.

**Reference values used in whale-score/technical-score tests:** computed via a standalone
reference script implementing the exact formulas from the design spec, hand-traced for
correctness — same approach as the technical-indicators plan. See each task's "Reference
calculation" note.

**Tech Stack:** Adds `anthropic` (official SDK) to the existing `httpx` / `pydantic-settings` /
stdlib `sqlite3` / stdlib `asyncio` stack. Tests: `pytest` + `pytest-asyncio` + `respx` (for
existing HTTP-based adapters, unaffected) + `unittest.mock` for the Anthropic client (the SDK
is designed to be mocked, not hit live in tests — see the design spec's Testing section on why
there's no real-network smoke test for this layer).

---

### Task 1: Package scaffolding and data model

**Files:**
- Create: `src/hello_coin/decision/__init__.py`
- Create: `src/hello_coin/decision/models.py`
- Test: `tests/decision/test_models.py`
- Create: `tests/decision/` (directory)

- [ ] **Step 1: Create the package**

Create `src/hello_coin/decision/__init__.py` (empty file).

Create the `tests/decision/` directory.

- [ ] **Step 2: Write the failing test**

Create `tests/decision/test_models.py`:

```python
from datetime import datetime, timezone

from hello_coin.decision.models import Decision


def test_decision_holds_fields():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        whale_score=0.49,
        technical_score=0.475,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Whale accumulation and bullish momentum align.",
        raw={"model": "claude-sonnet-5"},
    )

    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.raw == {"model": "claude-sonnet-5"}


def test_decision_allows_none_scores():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        whale_score=None,
        technical_score=0.475,
        weighted_score=None,
        action="hold",
        confidence=0.4,
        reasoning="No whale data available; technical signal alone is inconclusive.",
        raw={},
    )

    assert decision.whale_score is None
    assert decision.weighted_score is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.models'`

- [ ] **Step 4: Write the implementation**

Create `src/hello_coin/decision/models.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Decision:
    """One AI-made trade decision for a symbol at a point in time."""

    symbol: str
    timestamp: datetime
    whale_score: float | None
    technical_score: float | None
    weighted_score: float | None
    action: str  # "buy" | "sell" | "hold"
    confidence: float
    reasoning: str
    raw: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_models.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/decision/__init__.py src/hello_coin/decision/models.py tests/decision/test_models.py
git commit -m "Add decision-engine package scaffolding and Decision model"
```

---

### Task 2: Read methods on the existing whale and technical storage

**Files:**
- Modify: `src/hello_coin/ingestion/storage.py`
- Modify: `src/hello_coin/technical/storage.py`
- Modify: `tests/ingestion/test_storage.py`
- Modify: `tests/technical/test_storage.py`

Adds read methods only — no change to existing insert/count methods, schemas, or their tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_storage.py`:

```python
def test_recent_events_filters_by_symbol_case_insensitive_and_since():
    storage = WhaleStorage(":memory:")
    old_event = _event("a")  # symbol="BTC", timestamp=2026-08-22 (see _event() below)
    storage.insert_events([old_event])

    matching = storage.recent_events("btc", since=datetime(2026, 8, 21, tzinfo=timezone.utc))
    too_late = storage.recent_events("btc", since=datetime(2026, 8, 23, tzinfo=timezone.utc))
    wrong_symbol = storage.recent_events("eth", since=datetime(2026, 8, 21, tzinfo=timezone.utc))

    assert len(matching) == 1
    assert matching[0]["side"] == "buy"
    assert matching[0]["amount_usd"] == 60000.0
    assert too_late == []
    assert wrong_symbol == []


def test_recent_metrics_filters_by_symbol_case_insensitive_and_since():
    storage = WhaleStorage(":memory:")
    metric = WhaleMetric(
        source="binance",
        timestamp=datetime(2026, 8, 22, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        metric_name="top_trader_long_short_ratio",
        value=1.8,
        dedup_key="m1",
        raw={},
    )
    storage.insert_metrics([metric])

    matching = storage.recent_metrics("btcusdt", since=datetime(2026, 8, 21, tzinfo=timezone.utc))
    wrong_symbol = storage.recent_metrics("btc", since=datetime(2026, 8, 21, tzinfo=timezone.utc))

    assert len(matching) == 1
    assert matching[0]["metric_name"] == "top_trader_long_short_ratio"
    assert matching[0]["value"] == 1.8
    assert wrong_symbol == []
```

This reuses the existing `_event(dedup_key)` helper in that file, which builds a `WhaleEvent`
with `symbol="BTC"`, `side="buy"`, `amount_usd=60000.0` — add `from datetime import datetime,
timezone` to the file's imports if not already present (it already imports `datetime, timezone`
at the top per the existing file).

Append to `tests/technical/test_storage.py`:

```python
def test_latest_snapshot_returns_most_recent_row_for_symbol_and_timeframe():
    storage = TechnicalStorage(":memory:")
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 0, tzinfo=UTC)))
    storage.insert_snapshot(_snapshot(datetime(2026, 8, 22, 1, tzinfo=UTC)))

    latest = storage.latest_snapshot("BTCUSDT", "1h")

    assert latest is not None
    assert latest["timestamp"] == "2026-08-22T01:00:00+00:00"
    assert latest["rsi"] == 55.0


def test_latest_snapshot_returns_none_when_no_rows():
    storage = TechnicalStorage(":memory:")

    assert storage.latest_snapshot("ETHUSDT", "1h") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_storage.py tests/technical/test_storage.py -v`
Expected: FAIL — `AttributeError: 'WhaleStorage' object has no attribute 'recent_events'` (and
similarly for `recent_metrics` / `latest_snapshot`).

- [ ] **Step 3: Write the implementation**

In `src/hello_coin/ingestion/storage.py`, add two methods to `WhaleStorage` (after
`count_events`):

```python
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
        columns = (
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
        return [dict(zip(columns, row, strict=True)) for row in rows]

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
```

Add `from datetime import datetime` to the top of `src/hello_coin/ingestion/storage.py` (used
only for the type hint above — the existing file has no `datetime` import yet since it only
stored pre-serialized ISO strings).

In `src/hello_coin/technical/storage.py`, add one method to `TechnicalStorage` (after
`count_snapshots`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_storage.py tests/technical/test_storage.py -v`
Expected: all pass (existing tests + 4 new ones).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass — this task changes no existing behavior, only adds methods.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/storage.py src/hello_coin/technical/storage.py tests/ingestion/test_storage.py tests/technical/test_storage.py
git commit -m "Add read methods for whale/technical storage (decision engine inputs)"
```

---

### Task 3: Whale score

**Files:**
- Create: `src/hello_coin/decision/whale_score.py`
- Test: `tests/decision/test_whale_score.py`

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_whale_score.py`:

```python
import pytest

from hello_coin.decision.whale_score import base_asset, compute_whale_score

EVENTS = [
    {"side": "buy", "amount_usd": 100.0},
    {"side": "buy", "amount_usd": 200.0},
    {"side": "sell", "amount_usd": 50.0},
]

METRICS = [
    {"metric_name": "top_trader_long_short_ratio", "value": 1.5},
    {"metric_name": "long_short_account_ratio", "value": 2.0},
    {"metric_name": "some_other_metric", "value": 99.0},  # not "*ratio" suffixed — excluded
]


def test_base_asset_strips_known_quote_suffixes():
    assert base_asset("BTCUSDT") == "BTC"
    assert base_asset("ETHUSDC") == "ETH"
    assert base_asset("SOLUSD") == "SOL"
    assert base_asset("BTC") == "BTC"  # already a base asset, no suffix to strip


def test_compute_whale_score_combines_volume_and_ratio_bias():
    # Reference calculation:
    # volume_bias = (100+200-50)/(100+200+50) = 250/350 = 0.7142857142857143
    # ratio_bias = mean[(1.5-1)/(1.5+1), (2.0-1)/(2.0+1)] = mean[0.2, 0.3333333333333333]
    #            = 0.26666666666666666
    # whale_score = mean[0.7142857142857143, 0.26666666666666666] = 0.4904761904761905
    result = compute_whale_score(EVENTS, METRICS)
    assert result == pytest.approx(0.4904761904761905)


def test_compute_whale_score_uses_only_volume_bias_when_no_metrics():
    result = compute_whale_score(EVENTS, [])
    assert result == pytest.approx(0.7142857142857143)


def test_compute_whale_score_uses_only_ratio_bias_when_no_events():
    result = compute_whale_score([], METRICS)
    assert result == pytest.approx(0.26666666666666666)


def test_compute_whale_score_is_none_with_no_data():
    assert compute_whale_score([], []) is None


def test_compute_whale_score_ignores_events_without_directional_side():
    # A "position"/"transfer" event with side=None contributes nothing to volume_bias.
    events = [{"side": None, "amount_usd": 500.0}]
    assert compute_whale_score(events, []) is None


def test_compute_whale_score_ignores_metrics_not_named_ratio():
    metrics = [{"metric_name": "exchange_reserve", "value": 1234.0}]
    assert compute_whale_score([], metrics) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_whale_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.whale_score'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/whale_score.py`:

```python
_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


def base_asset(symbol: str) -> str:
    upper = symbol.upper()
    for suffix in _QUOTE_SUFFIXES:
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper[: -len(suffix)]
    return upper


def _volume_bias(events: list[dict]) -> float | None:
    relevant = [
        e for e in events if e.get("side") in ("buy", "sell") and e.get("amount_usd") is not None
    ]
    if not relevant:
        return None
    buy_usd = sum(e["amount_usd"] for e in relevant if e["side"] == "buy")
    sell_usd = sum(e["amount_usd"] for e in relevant if e["side"] == "sell")
    total = buy_usd + sell_usd
    return (buy_usd - sell_usd) / total if total > 0 else 0.0


def _ratio_bias(metrics: list[dict]) -> float | None:
    values = [
        m["value"]
        for m in metrics
        if m.get("metric_name", "").endswith("ratio")
        and m.get("value") is not None
        and m["value"] > -1
    ]
    if not values:
        return None
    normalized = [(v - 1) / (v + 1) for v in values]
    return sum(normalized) / len(normalized)


def compute_whale_score(events: list[dict], metrics: list[dict]) -> float | None:
    components = [c for c in (_volume_bias(events), _ratio_bias(metrics)) if c is not None]
    if not components:
        return None
    return sum(components) / len(components)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_whale_score.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/whale_score.py tests/decision/test_whale_score.py
git commit -m "Add whale score aggregation"
```

---

### Task 4: Technical score

**Files:**
- Create: `src/hello_coin/decision/technical_score.py`
- Test: `tests/decision/test_technical_score.py`

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_technical_score.py`:

```python
import pytest

from hello_coin.decision.technical_score import compute_technical_score


def test_compute_technical_score_combines_all_four_signals():
    # Reference calculation:
    # score_rsi(30) = (50-30)/50 = 0.4
    # score_macd(5) = 1.0 (positive histogram)
    # score_bb(close=105, upper=110, middle=100) = (100-105)/(110-100) = -0.5
    # score_ema(close=105, ema=100) = 1.0 (close above EMA)
    # technical_score = mean[0.4, 1.0, -0.5, 1.0] = 0.475
    snapshot = {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(0.475)


def test_score_rsi_clips_and_flips_sign_for_overbought():
    # Reference: score_rsi(70) = (50-70)/50 = -0.4 (overbought -> bearish/negative)
    snapshot = {
        "rsi": 70,
        "macd_histogram": None,
        "close_price": None,
        "bb_upper": None,
        "bb_middle": None,
        "ema": None,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(-0.4)


def test_bollinger_score_clips_when_price_beyond_upper_band():
    # Reference: raw (100-115)/(110-100) = -1.5, clipped to -1.0
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": 115,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": None,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(-1.0)


def test_compute_technical_score_is_none_when_all_fields_missing():
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": None,
        "bb_upper": None,
        "bb_middle": None,
        "ema": None,
    }
    assert compute_technical_score(snapshot) is None


def test_bollinger_score_is_excluded_when_bands_are_degenerate():
    # bb_upper == bb_middle (zero standard deviation) would divide by zero — excluded, not crashed.
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": 100,
        "bb_upper": 100,
        "bb_middle": 100,
        "ema": None,
    }
    assert compute_technical_score(snapshot) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_technical_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.technical_score'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/technical_score.py`:

```python
from typing import Any


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _score_rsi(rsi: float | None) -> float | None:
    if rsi is None:
        return None
    return _clip((50 - rsi) / 50, -1.0, 1.0)


def _score_macd(histogram: float | None) -> float | None:
    if histogram is None:
        return None
    if histogram > 0:
        return 1.0
    if histogram < 0:
        return -1.0
    return 0.0


def _score_bollinger(
    close_price: float | None, bb_upper: float | None, bb_middle: float | None
) -> float | None:
    if close_price is None or bb_upper is None or bb_middle is None:
        return None
    if bb_upper == bb_middle:
        return None
    return _clip((bb_middle - close_price) / (bb_upper - bb_middle), -1.0, 1.0)


def _score_ema(close_price: float | None, ema: float | None) -> float | None:
    if close_price is None or ema is None:
        return None
    if close_price > ema:
        return 1.0
    if close_price < ema:
        return -1.0
    return 0.0


def compute_technical_score(snapshot: dict[str, Any]) -> float | None:
    close_price = snapshot.get("close_price")
    components = [
        c
        for c in (
            _score_rsi(snapshot.get("rsi")),
            _score_macd(snapshot.get("macd_histogram")),
            _score_bollinger(close_price, snapshot.get("bb_upper"), snapshot.get("bb_middle")),
            _score_ema(close_price, snapshot.get("ema")),
        )
        if c is not None
    ]
    if not components:
        return None
    return sum(components) / len(components)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_technical_score.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/technical_score.py tests/decision/test_technical_score.py
git commit -m "Add technical score aggregation"
```

---

### Task 5: Anthropic LLM client

**Files:**
- Modify: `pyproject.toml` (already has `anthropic` added — commit it here since this is the
  first task that uses it)
- Create: `src/hello_coin/decision/llm.py`
- Test: `tests/decision/test_llm.py`

**Verified against the installed SDK** (see plan header): `AsyncAnthropic`, `messages.create(...,
tools=[...], tool_choice={"type": "tool", "name": ...})`, and the response's `content` list
containing a block with `.type == "tool_use"` and `.input: dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_llm.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hello_coin.decision.llm import DECIDE_TOOL, request_decision


def _tool_use_response(input_payload: dict):
    block = SimpleNamespace(type="tool_use", name="decide", input=input_payload)
    return SimpleNamespace(content=[block])


def _text_only_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


@pytest.mark.asyncio
async def test_request_decision_returns_tool_input():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_tool_use_response(
            {"action": "buy", "confidence": 0.8, "reasoning": "Whale accumulation."}
        )
    )

    result = await request_decision(
        mock_client, model="claude-sonnet-5", system="system prompt", user_message="user prompt"
    )

    assert result == {"action": "buy", "confidence": 0.8, "reasoning": "Whale accumulation."}
    mock_client.messages.create.assert_awaited_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert call_kwargs["system"] == "system prompt"
    assert call_kwargs["messages"] == [{"role": "user", "content": "user prompt"}]
    assert call_kwargs["tools"] == [DECIDE_TOOL]
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "decide"}


@pytest.mark.asyncio
async def test_request_decision_raises_when_no_tool_use_block():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_text_only_response("I refuse."))

    with pytest.raises(RuntimeError, match="did not include a decide tool call"):
        await request_decision(
            mock_client, model="claude-sonnet-5", system="system prompt", user_message="user prompt"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.llm'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/llm.py`:

```python
from typing import Any

DECIDE_TOOL = {
    "name": "decide",
    "description": "Record a trading decision (action, confidence, reasoning) for a crypto symbol.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["action", "confidence", "reasoning"],
    },
}


async def request_decision(
    client: Any, model: str, system: str, user_message: str
) -> dict[str, Any]:
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        tools=[DECIDE_TOOL],
        tool_choice={"type": "tool", "name": "decide"},
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Anthropic response did not include a decide tool call")
```

`client` is typed `Any` rather than `anthropic.AsyncAnthropic` — this keeps the function trivial
to unit test with a plain mock (matching the test above) without importing the SDK's types just
for a type hint.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_llm.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/hello_coin/decision/llm.py tests/decision/test_llm.py
git commit -m "Add Anthropic tool-use client for trade decisions"
```

---

### Task 6: Decision service (orchestration)

**Files:**
- Create: `src/hello_coin/decision/service.py`
- Test: `tests/decision/test_service.py`

Combines whale score + technical score + LLM call into one `Decision`. Symbol matching for
whale data follows the design spec: events matched by `base_asset(symbol)`; metrics matched by
**either** the full symbol **or** `base_asset(symbol)` (two storage reads, merged).

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_service.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.service import compute_decision


@pytest.mark.asyncio
async def test_compute_decision_combines_scores_and_calls_llm():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = [{"side": "buy", "amount_usd": 300.0}]
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
        "atr": 2.0,
    }

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "buy", "confidence": 0.8, "reasoning": "Aligned signals."}
        ),
    ) as mock_request_decision:
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.symbol == "BTCUSDT"
    assert decision.whale_score == pytest.approx(1.0)  # all-buy volume_bias
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.weighted_score == pytest.approx(0.7 * 1.0 + 0.3 * 0.475)
    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.reasoning == "Aligned signals."

    whale_storage.recent_events.assert_called_once()
    args, kwargs = whale_storage.recent_events.call_args
    assert args[0] == "BTC"  # base_asset("BTCUSDT")
    assert whale_storage.recent_metrics.call_count == 2  # full symbol + base asset
    mock_request_decision.assert_awaited_once()
    call_kwargs = mock_request_decision.call_args.kwargs
    assert call_kwargs["client"] is anthropic_client
    assert call_kwargs["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_compute_decision_reports_missing_data_without_reweighting():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = []
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
        "atr": 2.0,
    }

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "hold", "confidence": 0.3, "reasoning": "No whale data."}
        ),
    ):
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.whale_score is None
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.weighted_score is None  # never re-weighted to 100% technical
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.service'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/service.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any

from hello_coin.decision.llm import request_decision
from hello_coin.decision.models import Decision
from hello_coin.decision.technical_score import compute_technical_score
from hello_coin.decision.whale_score import base_asset, compute_whale_score

SYSTEM_PROMPT = (
    "You are a crypto trading decision assistant for the hello-coin system. Whale activity "
    "carries roughly 70% of the decision weight and technical indicators roughly 30% — treat "
    "the provided whale_score and technical_score accordingly, not as equally weighted inputs. "
    "Scores range from -1 (strongly bearish) to +1 (strongly bullish); a missing score means "
    "that data source had nothing usable this cycle, not that it's neutral — factor the gap "
    "into your confidence rather than ignoring it. Always call the decide tool."
)


def _build_user_message(
    symbol: str,
    whale_score: float | None,
    technical_score: float | None,
    weighted_score: float | None,
    snapshot: dict[str, Any] | None,
) -> str:
    lines = [f"Symbol: {symbol}"]
    lines.append(f"whale_score: {whale_score if whale_score is not None else 'unavailable'}")
    lines.append(
        f"technical_score: {technical_score if technical_score is not None else 'unavailable'}"
    )
    lines.append(
        f"weighted_score (0.7*whale + 0.3*technical): "
        f"{weighted_score if weighted_score is not None else 'unavailable (one or both inputs missing)'}"
    )
    if snapshot is not None:
        lines.append(
            "Latest technical readings: "
            f"close={snapshot.get('close_price')}, rsi={snapshot.get('rsi')}, "
            f"macd_histogram={snapshot.get('macd_histogram')}, "
            f"bollinger=({snapshot.get('bb_lower')}, {snapshot.get('bb_middle')}, "
            f"{snapshot.get('bb_upper')}), ema={snapshot.get('ema')}, atr={snapshot.get('atr')}"
        )
    return "\n".join(lines)


async def compute_decision(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
) -> Decision:
    since = datetime.now(tz=UTC) - timedelta(hours=whale_lookback_hours)
    asset = base_asset(symbol)

    events = whale_storage.recent_events(asset, since)
    metrics = whale_storage.recent_metrics(symbol, since) + whale_storage.recent_metrics(
        asset, since
    )
    whale_score = compute_whale_score(events, metrics)

    snapshot = technical_storage.latest_snapshot(symbol, timeframe)
    technical_score = compute_technical_score(snapshot) if snapshot is not None else None

    weighted_score = (
        0.7 * whale_score + 0.3 * technical_score
        if whale_score is not None and technical_score is not None
        else None
    )

    user_message = _build_user_message(symbol, whale_score, technical_score, weighted_score, snapshot)
    result = await request_decision(
        client=anthropic_client, model=model, system=SYSTEM_PROMPT, user_message=user_message
    )

    return Decision(
        symbol=symbol,
        timestamp=datetime.now(tz=UTC),
        whale_score=whale_score,
        technical_score=technical_score,
        weighted_score=weighted_score,
        action=result["action"],
        confidence=float(result["confidence"]),
        reasoning=result["reasoning"],
        raw=result,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_service.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/service.py tests/decision/test_service.py
git commit -m "Add decision service combining whale/technical scores with the LLM call"
```

---

### Task 7: SQLite storage

**Files:**
- Create: `src/hello_coin/decision/storage.py`
- Test: `tests/decision/test_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_storage.py`:

```python
from datetime import UTC, datetime

from hello_coin.decision.models import Decision
from hello_coin.decision.storage import DecisionStorage


def _decision(timestamp: datetime) -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=timestamp,
        whale_score=0.49,
        technical_score=0.475,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Aligned signals.",
        raw={"model": "claude-sonnet-5"},
    )


def test_insert_decision_returns_count_and_dedupes():
    storage = DecisionStorage(":memory:")
    first = _decision(datetime(2026, 8, 22, 0, tzinfo=UTC))
    second = _decision(datetime(2026, 8, 22, 0, tzinfo=UTC))  # same symbol/timestamp
    third = _decision(datetime(2026, 8, 22, 1, tzinfo=UTC))

    inserted_first = storage.insert_decision(first)
    inserted_second = storage.insert_decision(second)
    inserted_third = storage.insert_decision(third)

    assert inserted_first == 1
    assert inserted_second == 0
    assert inserted_third == 1
    assert storage.count_decisions() == 2
    assert storage.count_decisions(symbol="BTCUSDT") == 2
    assert storage.count_decisions(symbol="ETHUSDT") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.storage'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/storage.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_storage.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/storage.py tests/decision/test_storage.py
git commit -m "Add SQLite-backed DecisionStorage with dedup on insert"
```

---

### Task 8: Scheduler

**Files:**
- Create: `src/hello_coin/decision/scheduler.py`
- Test: `tests/decision/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/decision/test_scheduler.py`:

```python
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.models import Decision
from hello_coin.decision.scheduler import poll_once, run_symbol_loop
from hello_coin.decision.storage import DecisionStorage


def _decision() -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        whale_score=0.49,
        technical_score=0.475,
        weighted_score=0.485,
        action="buy",
        confidence=0.8,
        reasoning="Aligned signals.",
        raw={},
    )


@pytest.mark.asyncio
async def test_poll_once_inserts_decision_and_returns_count():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(return_value=_decision()),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 1
    assert storage.count_decisions() == 1


@pytest.mark.asyncio
async def test_poll_once_returns_zero_and_logs_on_failure():
    storage = DecisionStorage(":memory:")
    with patch(
        "hello_coin.decision.scheduler.compute_decision",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        inserted = await poll_once(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
        )

    assert inserted == 0
    assert storage.count_decisions() == 0


@pytest.mark.asyncio
async def test_run_symbol_loop_stops_when_event_set_during_poll():
    storage = DecisionStorage(":memory:")
    stop_event = asyncio.Event()
    call_count = 0

    async def _fake_compute_decision(**kwargs):
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return _decision()

    with patch("hello_coin.decision.scheduler.compute_decision", new=_fake_compute_decision):
        await run_symbol_loop(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=MagicMock(),
            technical_storage=MagicMock(),
            anthropic_client=MagicMock(),
            model="claude-sonnet-5",
            whale_lookback_hours=24,
            storage=storage,
            stop_event=stop_event,
            poll_interval_seconds=0,
        )

    assert call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hello_coin.decision.scheduler'`

- [ ] **Step 3: Write the implementation**

Create `src/hello_coin/decision/scheduler.py`:

```python
import asyncio
import logging
from typing import Any

from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 3600  # 1 hour — matches the technical layer's 1h candle default


async def poll_once(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
) -> int:
    try:
        decision = await compute_decision(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
        )
    except Exception:
        logger.exception("%s: decision failed", symbol)
        return 0
    return storage.insert_decision(decision)


async def run_symbol_loop(
    symbol: str,
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    stop_event: asyncio.Event,
    poll_interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        inserted = await poll_once(
            symbol=symbol,
            timeframe=timeframe,
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            anthropic_client=anthropic_client,
            model=model,
            whale_lookback_hours=whale_lookback_hours,
            storage=storage,
        )
        logger.info("%s: inserted %d new decision(s)", symbol, inserted)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def run_forever(
    symbols: list[str],
    timeframe: str,
    whale_storage: Any,
    technical_storage: Any,
    anthropic_client: Any,
    model: str,
    whale_lookback_hours: int,
    storage: DecisionStorage,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    stop_event = asyncio.Event()
    await asyncio.gather(
        *(
            run_symbol_loop(
                symbol=symbol,
                timeframe=timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                anthropic_client=anthropic_client,
                model=model,
                whale_lookback_hours=whale_lookback_hours,
                storage=storage,
                stop_event=stop_event,
                poll_interval_seconds=poll_interval_seconds,
            )
            for symbol in symbols
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_scheduler.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hello_coin/decision/scheduler.py tests/decision/test_scheduler.py
git commit -m "Add decision-engine scheduler"
```

---

### Task 9: Config and CLI wiring

**Files:**
- Modify: `src/hello_coin/ingestion/config.py`
- Modify: `src/hello_coin/cli.py`
- Modify: `tests/ingestion/test_config.py`
- Modify: `tests/test_cli.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_config.py`:

```python
def test_decision_settings_default(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "DECISION_WHALE_LOOKBACK_HOURS"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.decision_whale_lookback_hours == 24


def test_decision_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    monkeypatch.setenv("DECISION_WHALE_LOOKBACK_HOURS", "12")

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.anthropic_model == "claude-opus-5"
    assert settings.decision_whale_lookback_hours == 12
```

Append to `tests/test_cli.py`:

```python
def test_decision_run_parses():
    parser = build_parser()

    args = parser.parse_args(["decision", "run"])

    assert args.command == "decision"
    assert args.decision_command == "run"


def test_decision_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["decision", "test", "BTCUSDT"])

    assert args.command == "decision"
    assert args.decision_command == "test"
    assert args.symbol == "BTCUSDT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_config.py tests/test_cli.py -v`
Expected: FAIL — `anthropic_api_key` doesn't exist on `Settings`; `decision` isn't a valid
subcommand yet.

- [ ] **Step 3: Write the implementation**

In `src/hello_coin/ingestion/config.py`, add three fields to `Settings` (after
`technical_timeframe`):

```python
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    decision_whale_lookback_hours: int = 24
```

Edit `.env.example`, append:

```
# Anthropic API key (console.anthropic.com) for the AI decision engine. Every call costs money —
# there's no free tier for this one. ANTHROPIC_MODEL defaults to claude-sonnet-5.
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
DECISION_WHALE_LOOKBACK_HOURS=24
```

Replace the contents of `src/hello_coin/cli.py`:

```python
import argparse
import asyncio
import logging

from anthropic import AsyncAnthropic

from hello_coin.decision.scheduler import run_forever as run_decision_forever
from hello_coin.decision.service import compute_decision
from hello_coin.decision.storage import DecisionStorage
from hello_coin.ingestion.config import Settings
from hello_coin.ingestion.registry import build_adapters
from hello_coin.ingestion.scheduler import run_forever as run_ingestion_forever
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.scheduler import run_forever as run_technical_forever
from hello_coin.technical.service import compute_snapshot
from hello_coin.technical.storage import TechnicalStorage

DEFAULT_WHALE_DB_PATH = "data/whale.db"
DEFAULT_TECHNICAL_DB_PATH = "data/technical.db"
DEFAULT_DECISION_DB_PATH = "data/decisions.db"


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

    decision_parser = subparsers.add_parser("decision", help="AI decision engine commands")
    decision_subparsers = decision_parser.add_subparsers(dest="decision_command", required=True)
    decision_subparsers.add_parser("run", help="Run the decision engine continuously")
    decision_test_parser = decision_subparsers.add_parser(
        "test", help="Compute one decision for a symbol and print the result"
    )
    decision_test_parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")

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


async def _run_decision() -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    decision_storage = DecisionStorage(DEFAULT_DECISION_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            await run_decision_forever(
                symbols=settings.exchange_watch_symbols,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
                storage=decision_storage,
            )
    finally:
        whale_storage.close()
        technical_storage.close()
        decision_storage.close()


async def _test_decision(symbol: str) -> None:
    settings = Settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — the decision engine is not configured.")
        return
    whale_storage = WhaleStorage(DEFAULT_WHALE_DB_PATH)
    technical_storage = TechnicalStorage(DEFAULT_TECHNICAL_DB_PATH)
    try:
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            decision = await compute_decision(
                symbol=symbol,
                timeframe=settings.technical_timeframe,
                whale_storage=whale_storage,
                technical_storage=technical_storage,
                anthropic_client=client,
                model=settings.anthropic_model,
                whale_lookback_hours=settings.decision_whale_lookback_hours,
            )
        print(decision)
    finally:
        whale_storage.close()
        technical_storage.close()


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
    elif args.command == "decision" and args.decision_command == "run":
        asyncio.run(_run_decision())
    elif args.command == "decision" and args.decision_command == "test":
        asyncio.run(_test_decision(args.symbol))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_config.py tests/test_cli.py -v`
Expected: all pass (14 config tests, 6 CLI tests).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/hello_coin/ingestion/config.py src/hello_coin/cli.py .env.example tests/ingestion/test_config.py tests/test_cli.py
git commit -m "Wire decision-engine config and CLI commands"
```

---

### Task 10: Docs and manual verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

No automated real-network smoke test for this layer — every Anthropic API call costs real
money (see the design spec's Testing section). Manual verification is documented instead, same
treatment as the paid whale-data adapters.

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, in the `## Architecture` section, after the `technical/` bullet list (before
the CLI entry-point sentence), add:

```markdown
`src/hello_coin/decision/` is the AI decision engine (combines the two signals above), see
`docs/superpowers/specs/2026-08-22-decision-engine-design.md`:

- `models.py` — `Decision` (symbol, scores, action/confidence/reasoning, raw LLM response).
- `whale_score.py` — aggregates recent `data/whale.db` rows into `[-1, 1]` (or `None`);
  `base_asset()` handles the symbol-convention mismatch across whale sources (documented
  limitation — see the spec).
- `technical_score.py` — aggregates the latest `data/technical.db` snapshot into `[-1, 1]` (or
  `None`) from RSI/MACD/Bollinger/EMA.
- `llm.py` — calls the Anthropic API via tool use for a structured `action`/`confidence`/
  `reasoning` decision. No real-network test — every call costs money.
- `service.py` — combines both scores (0.7/0.3, never silently re-weighted when one is missing)
  into the LLM prompt and parses the result into a `Decision`.
- `storage.py` — SQLite (`data/decisions.db`, gitignored) with dedup on `(symbol, timestamp)`.
- `scheduler.py` — polls every symbol in `exchange_watch_symbols` every 1 hour.
```

Update the CLI entry-point sentence to:

```markdown
`src/hello_coin/cli.py` is the entry point: `hello-coin ingest run` / `hello-coin technical run`
/ `hello-coin decision run` start the three services; `hello-coin ingest test <source>` /
`hello-coin technical test <symbol>` / `hello-coin decision test <symbol>` fetch, compute, or
decide once and print the result.
```

Replace:

```markdown
No decision engine or trade execution code exists yet — those are separate, not-yet-planned
pieces of the product intent below.
```

with:

```markdown
No trade execution code exists yet — placing real orders needs the target exchange(s) confirmed
with the user first (see the "Tooling" section below), which hasn't happened.
```

- [ ] **Step 2: Update README.md**

In `README.md`, add a new section after `## Technical indicators`:

```markdown
## Decision engine

1. Register an Anthropic API key at [console.anthropic.com](https://console.anthropic.com) and
   set `ANTHROPIC_API_KEY` in `.env`. Every call costs money — there's no free tier.
2. Compute one decision to sanity-check it: `uv run hello-coin decision test BTCUSDT`
   (needs `data/whale.db` and `data/technical.db` to already have some rows — run `ingest run`/
   `technical run` for a bit first, or the scores will both come back `None` and the LLM will
   see "unavailable" for everything).
3. Run the service continuously: `uv run hello-coin decision run` — writes to
   `data/decisions.db`. Polls once per hour per symbol.
```

- [ ] **Step 3: Manually verify against the real Anthropic API**

```bash
uv run hello-coin ingest test hyperliquid    # populate some whale data first, if not already
uv run hello-coin technical test BTCUSDT     # confirm technical.db has a row
uv run hello-coin decision test BTCUSDT
```

Expected: prints one `Decision(...)` with a real `action`/`confidence`/`reasoning` from Claude,
and non-`None` `whale_score`/`technical_score` if `ingest run` had populated recent whale rows
for BTC.

- [ ] **Step 4: Run the full test suite one last time**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Document the decision engine and how to run it"
```
