# Whale Position Skew Alerts — design

Date: 2026-08-30

## Problem

The current Hyperdash whale-position notification (`PositionChangeTracker` →
`PositionChange` → `TelegramNotifier`) fires one Telegram message per wallet every time it
opens or closes a position. With several whales tracked per coin this is noisy and doesn't
answer the question the project owner actually cares about: *is the tracked whale money on one
coin lopsidedly LONG or SHORT right now, and is that skew building or unwinding?*

This design replaces the per-wallet open/close notification with a per-coin aggregate
LONG/SHORT skew alert, computed from the same Hyperdash position data already fetched every
poll — no new data source, no database round-trip.

## Where skew is computed

`HyperdashAdapter.fetch()` already builds `observed: dict[(address, coin), WhaleEvent]` — the
full set of currently-active positions among tracked wallets for every watched coin, rebuilt
fresh on every poll. This is exactly the data needed; no query against `whale.db` is required.

After building `observed`, `fetch()` groups it by coin and sums `amount_usd` by side (`buy` →
long, `sell` → short) to get `(long_usd, short_usd)` per coin. Each coin's totals are handed to
an in-memory `SkewTracker` (one instance per adapter, keyed by coin) which decides whether this
crosses into or out of a "dominant" zone. Any resulting alerts are queued and exposed through a
new `consume_skew_alerts()` method, replacing `consume_position_changes()`.

`scheduler.poll_once()` calls `adapter.consume_skew_alerts()` (instead of
`consume_position_changes()`) after persisting events, and hands each `SkewAlert` to
`notifier.notify(alert)`.

## Thresholds and hysteresis

Each coin has one of three states, tracked independently:

- `neutral`
- `long_dominant`
- `short_dominant`

Percentages are `long_pct = long_usd / (long_usd + short_usd)` and `short_pct = 1 - long_pct`,
or `(0.0, 0.0)` when `long_usd + short_usd <= 0` (no tracked positions for that coin at all).
Treating "no data" as `(0.0, 0.0)` rather than skipping the update is deliberate: it makes "every
tracked whale closed out" behave exactly like "the dominant side fell to 0%", which correctly
fires an exit alert if the coin was previously in a dominant zone, while correctly staying
`neutral` with no alert before any position has ever been observed (0% is never above 75%).

Transitions:

- From `neutral`: `long_pct > 0.75` → `long_dominant` (alert: entering, "LONG dominant"). Else
  `short_pct > 0.75` → `short_dominant` (alert: entering, "SHORT dominant"). Otherwise stays
  `neutral`, no alert.
- From `long_dominant`: `long_pct < 0.70` → back to `neutral` (alert: exiting, "LONG cooling
  off"). Otherwise stays `long_dominant`, no alert, even if `long_pct` wobbles within
  [0.70, 1.0].
- From `short_dominant`: symmetric, using `short_pct`.

The 70–75% dead zone is deliberate hysteresis: it prevents an alert firing on every poll while
the ratio hovers near one threshold. An alert only fires on an actual state transition, so a
coin that has been sitting at 80% long for hours produces exactly one alert (when it first
crossed 75%) until something actually changes enough to cross back below 70%.

No baseline-suppression is needed (unlike the old open/close feature): if a coin is already
skewed >75% the very first time the adapter polls, that's real, useful information and should
alert immediately rather than being swallowed as "just establishing a baseline."

## Alert content (Vietnamese)

`SkewAlert` carries `coin`, `zone` (the dominant zone entered or exited), `direction`
(`"enter"`/`"exit"`), `long_usd`, `short_usd`, `long_pct`, `short_pct`. `TelegramNotifier`
formats a two-line message (title + body, same `f"{title}\n{body}"` delivery as today) in
Vietnamese:

```
Enter long_dominant:   "LINK: LONG áp đảo (82%)"
                        "Long $820,000 vs Short $180,000 (tổng $1,000,000)"

Enter short_dominant:  "LINK: SHORT áp đảo (82%)"
                        "Short $820,000 vs Long $180,000 (tổng $1,000,000)"

Exit long_dominant:    "LINK: LONG hạ nhiệt (68%)"
                        "Long $680,000 vs Short $320,000 — có thể đang thoát lệnh"

Exit short_dominant:   "LINK: SHORT hạ nhiệt (68%)"
                        "Short $680,000 vs Long $320,000 — có thể đang thoát lệnh"
```

The percentage shown is always the percentage of the zone's own side (e.g. `long_pct` for a
`long_dominant` alert, whether entering or exiting).

## Removed

The whole open/close notification mechanism is deleted, not deprecated — nothing else in the
codebase depends on it:

- `src/hello_coin/ingestion/position_changes.py` (`PositionChangeTracker`) — deleted.
- `PositionChange` in `src/hello_coin/ingestion/models.py` — deleted.
- `Adapter.consume_position_changes()` in `src/hello_coin/ingestion/adapters/base.py` — replaced
  by `Adapter.consume_skew_alerts() -> list[SkewAlert]`, default `[]`.
- `HyperdashAdapter._position_tracker` / `_pending_position_changes` — replaced by
  `_skew_tracker: SkewTracker` / `_pending_skew_alerts: list[SkewAlert]`.
  `_active_wallets_by_coin` tracking (which wallets are currently considered "active" for a coin,
  independent of the top-delta qualifying threshold) is unrelated to open/close detection and is
  kept unchanged — it's still needed to keep `observed` accurate.
- `format_position_notification()` / `_short_wallet()` in `notifications.py` — replaced by a new
  Vietnamese `format_skew_notification(alert: SkewAlert) -> tuple[str, str]`.
- Old tests: `tests/ingestion/test_position_changes.py`, the three open/close-detection tests in
  `tests/ingestion/test_hyperdash.py` (`test_fetch_second_refresh_reports_open_after_silent_baseline`,
  `test_fetch_rechecks_prior_wallet_and_reports_confirmed_close`,
  `test_fetch_does_not_close_position_when_prior_wallet_recheck_fails`), and the
  `PositionChange`-based tests in `test_base.py`, `test_scheduler.py`, `test_notifications.py`.

## New

- `src/hello_coin/ingestion/position_skew.py` — pure, framework-free:
  - `compute_skew(long_usd: float, short_usd: float) -> tuple[float, float]` (returns `(0.0,
    0.0)` for a zero-or-negative total instead of raising)
  - `next_zone(current: SkewZone, long_pct: float, short_pct: float) -> SkewZone`
  - `@dataclass(frozen=True) class SkewAlert` (`coin`, `zone`, `direction`, `long_usd`,
    `short_usd`, `long_pct`, `short_pct`)
  - `class SkewTracker` — stateful, `update(coin, long_usd, short_usd) -> SkewAlert | None`

## Testing

- `position_skew.py` gets full unit coverage with zero mocking: threshold crossings in both
  directions, staying within a dominant zone not re-alerting, the 70–75% dead zone, a zero
  total staying `neutral` from a fresh tracker (no alert), and a zero total from a dominant
  zone firing an exit alert.
- `HyperdashAdapter` tests: replace the three open/close tests with tests that drive two
  consecutive `fetch()` calls through a long-skew scenario and assert `consume_skew_alerts()`
  returns the expected enter/exit `SkewAlert`s; keep every other existing `test_hyperdash.py`
  test (delta filtering, error isolation, position parsing) unchanged since `observed`/
  `_active_wallets_by_coin` bookkeeping is untouched.
- `scheduler.py` tests: update the notifier fixtures in `test_scheduler.py` to use
  `consume_skew_alerts()`/`SkewAlert` instead of `consume_position_changes()`/`PositionChange`.
- `notifications.py` tests: replace `format_position_notification` tests with
  `format_skew_notification` tests covering all four message variants above; keep the existing
  Telegram-delivery tests (no-op without token/chat id, HTTP failure logged) unchanged except for
  swapping the payload type.
