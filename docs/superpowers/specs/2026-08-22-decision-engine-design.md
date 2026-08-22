# Decision Engine — Design

Date: 2026-08-22
Status: Approved by user, pending implementation plan

## Purpose

hello-coin combines whale activity (~70% weight) and technical indicators (~30% weight) to
decide crypto trade entries/exits, using AI for the final call — both signal-source layers
(`ingestion/`, `technical/`) are complete. This design covers the third piece: a service that,
per symbol, aggregates recent whale data and the latest technical snapshot into two normalized
scores, sends them (plus supporting raw numbers) to the Anthropic API, and stores the resulting
`Decision` (action, confidence, reasoning).

**Per explicit user confirmation during design:** "use AI to decide" means a real Claude API
call per decision cycle (not a pure arithmetic formula) — the 70/30-weighted scores are
*inputs* the LLM reasons over, not the decision itself.

## Scope

- One package, `src/hello_coin/decision/`, sibling to `ingestion/` and `technical/`.
- Per watched symbol (reuses `exchange_watch_symbols`), every poll:
  1. Compute a **whale score** in `[-1, 1]` (or `None`) from recent rows in `data/whale.db`.
  2. Compute a **technical score** in `[-1, 1]` (or `None`) from the latest row in
     `data/technical.db`.
  3. Call the Anthropic API with both scores, the 70/30 weighted combination (when both are
     available), and supporting raw numbers; get back a structured `action` (`buy`/`sell`/
     `hold`), `confidence` (0–1), and `reasoning`.
  4. Store one `Decision` row in `data/decisions.db`.
- Poll every **1 hour** (matches the technical layer's default `1h` candle timeframe — deciding
  faster than the underlying technical data updates wastes API calls for no new information).

Explicitly out of scope: trade execution (placing real orders) — CLAUDE.md requires confirming
the target exchange(s) with the user before that work starts, which hasn't happened yet.

## Whale score

**Data access:** `WhaleStorage` (existing, `ingestion/storage.py`) gains two new read methods:
`recent_events(symbol: str, since: datetime) -> list[dict]` and
`recent_metrics(symbol: str, since: datetime) -> list[dict]`, each returning raw rows matched by
symbol within a lookback window (default 24h, configurable). No change to existing insert/count
methods or their tests.

**Symbol matching is the hard part** — the eleven whale sources record `symbol` in inconsistent
conventions (Hyperliquid: `"BTC"`; the four exchange derivatives adapters: the full pair, e.g.
`"BTCUSDT"`; CryptoQuant: `"BTC"`; Etherscan: the chain's native token, e.g. `"ETH"`; Nansen/
Whale Alert/Bitquery: whatever token was actually transferred, e.g. `"USDC"`, `"weth"`; DeBank:
always `"USD"`, not asset-specific). This design does **not** attempt a universal token-mapping
table — that's a much bigger problem than this engine needs to solve today. Instead:

- Derive `base_asset(symbol)`: strip a trailing `USDT`/`USDC`/`USD` from the watched symbol
  (e.g. `"BTCUSDT"` → `"BTC"`), case-insensitive comparison throughout.
- Match `WhaleEvent` rows where `symbol` (case-insensitive) equals `base_asset` — picks up
  Hyperliquid and Etherscan reliably; incidentally picks up Nansen/Whale Alert/Bitquery rows
  only when the transferred token happens to equal the base asset (e.g. a raw BTC-wrapped-token
  transfer), which is correct behavior, not a bug — those adapters aren't asset-filtered by
  design (see their own plans).
- Match `WhaleMetric` rows where `symbol` (case-insensitive) equals **either** the full watched
  symbol (`"BTCUSDT"`, matches the four exchange adapters) **or** `base_asset` (`"BTC"`, matches
  CryptoQuant).
- DeBank's `"USD"`-symbol position snapshots are never asset-matched by this logic — they're a
  portfolio-value signal, not a per-asset directional one, and are correctly excluded from a
  per-symbol whale score.

This matching rule is a known, documented simplification — not silently wrong, just narrower
than a hypothetical full token-identity system. Worth revisiting once more sources are added.

**Scoring formulas:**

```
volume_bias = None if no matching WhaleEvent rows have side in {"buy","sell"} and amount_usd
              is not None; else:
    buy_usd = sum(amount_usd for side == "buy")
    sell_usd = sum(amount_usd for side == "sell")
    total = buy_usd + sell_usd
    volume_bias = (buy_usd - sell_usd) / total if total > 0 else 0.0

ratio_bias = None if no matching WhaleMetric rows have metric_name ending in "ratio"; else:
    normalized = [(v - 1) / (v + 1) for v in those values if v > -1]
    ratio_bias = mean(normalized)   # ratio > 1 (more long) -> positive; < 1 -> negative

whale_score = mean of whichever of [volume_bias, ratio_bias] is not None
            = None if both are None (never fabricated as 0)
```

`(v - 1) / (v + 1)` maps a long/short ratio of 1.0 (balanced) to 0, > 1 (net long) to a positive
number approaching 1 as the ratio grows, and < 1 (net short) to a negative number approaching -1
as the ratio approaches 0 — a standard bounded transform for a positive ratio around 1.

## Technical score

Reads `TechnicalStorage`'s (existing, `technical/storage.py`) latest row for the symbol —
`TechnicalStorage` gains a `latest_snapshot(symbol: str, timeframe: str) -> dict | None` read
method (no change to existing insert/count methods or their tests).

```
score_rsi  = None if rsi is None else clip((50 - rsi) / 50, -1, 1)
             # RSI mean-reversion: overbought (>50) -> negative, oversold (<50) -> positive
score_macd = None if macd_histogram is None else
             (1.0 if histogram > 0 else -1.0 if histogram < 0 else 0.0)
             # MACD trend-following: positive histogram -> bullish momentum
score_bb   = None if any of bb_upper/bb_middle/close_price is None, or bb_upper == bb_middle,
             else clip((bb_middle - close_price) / (bb_upper - bb_middle), -1, 1)
             # Bollinger mean-reversion: price above upper band -> negative (overbought)
score_ema  = None if ema is None else
             (1.0 if close_price > ema else -1.0 if close_price < ema else 0.0)
             # EMA trend-following: price above EMA -> bullish

technical_score = mean of whichever of [score_rsi, score_macd, score_bb, score_ema] is not None
                = None if all are None
```

`atr` is surfaced to the LLM as volatility context (see below) but doesn't feed the score — it's
a magnitude, not a direction.

## Combining scores and calling the LLM

```
weighted_score = 0.7 * whale_score + 0.3 * technical_score
                 ONLY when both whale_score and technical_score are not None; otherwise None.
```

This deliberately does **not** re-weight to 100% of whichever single score is available — per
CLAUDE.md, the 70/30 split must be preserved, not silently changed when data is missing. When
one or both scores are `None`, `weighted_score` stays `None` and the LLM prompt says so
explicitly, so *it* reasons about the gap rather than the code quietly reweighting.

**LLM call:** Anthropic SDK (`anthropic.AsyncAnthropic`), model configurable (default
`claude-sonnet-5`). The prompt includes: the symbol, `whale_score`/`technical_score`/
`weighted_score` (or "unavailable"), the raw supporting numbers (buy/sell USD volume, ratio
values, RSI/MACD/Bollinger/EMA/ATR/close price), and asks for a decision via **tool use** — a
`decide` tool with a JSON schema (`action`: enum `buy`/`sell`/`hold`, `confidence`: number 0–1,
`reasoning`: string) — forcing structured, parseable output instead of free text.

## Data model

```python
@dataclass
class Decision:
    symbol: str
    timestamp: datetime
    whale_score: float | None
    technical_score: float | None
    weighted_score: float | None
    action: str          # "buy" | "sell" | "hold"
    confidence: float
    reasoning: str
    raw: dict             # full LLM response content, for debugging/audit
```

## Storage

SQLite `data/decisions.db` (gitignored). One table:

```sql
CREATE TABLE decisions (
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
```

## Config

```python
anthropic_api_key: str | None = None
anthropic_model: str = "claude-sonnet-5"
decision_whale_lookback_hours: int = 24
```

No new symbol list — reuses `exchange_watch_symbols`. Poll interval (1 hour) is a constant in
`scheduler.py`, matching the pattern already used for the technical layer's 15-minute constant
(not user-configurable in this first version — YAGNI until a real need for tuning appears).

## Error handling

Same posture as the other two layers: a failed API call (network error, rate limit, malformed
tool response) is logged and the scheduler continues to the next symbol/tick — never crashes the
service. A missing `ANTHROPIC_API_KEY` means the decision engine reports itself unconfigured
(mirrors every ingestion adapter's `is_configured()` pattern) and the CLI's `decision run` command
explains why nothing is happening rather than silently doing nothing.

## Testing

- `whale_score.py` and `technical_score.py`: pure functions tested against hand-computable
  reference values (same rigor as `technical/indicators.py`), zero mocking, zero live data.
- `llm.py`: tested against a mocked Anthropic client (the SDK is designed for this — no real API
  calls in the test suite).
- `service.py`: tested with mocked storage reads and a mocked LLM call, asserting the full
  wiring (scores → prompt → parsed `Decision`).
- One real-network smoke test is **not** included here (unlike the no-auth Hyperliquid/Binance/
  klines smoke tests) — every Anthropic API call costs real money, so there is no free "hit the
  real endpoint" smoke test for this layer. Manual verification (documented in the plan) is the
  only way to confirm the real API integration works, same as the paid whale-data adapters.

## Open items for the implementation plan

- Exact task breakdown and ordering (storage read-method additions → score functions → LLM
  client → service → storage → scheduler → CLI wiring) — a planning decision.
- Exact Anthropic tool-use request/response shape to code against — verified against the
  `anthropic` SDK's own documented types during planning, not guessed.
