from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_coin.decision.service import compute_decision
from hello_coin.liquidation.models import LiquidationBucket, LiquidationSnapshot


def _liquidation_snapshot() -> LiquidationSnapshot:
    # Single short cluster at 105 with current_price=100 -> distance_pct=0.05,
    # weighted_short=1,000,000/0.05=20,000,000, weighted_long=0 -> score=1.0
    return LiquidationSnapshot(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        current_price=100.0,
        buckets=[LiquidationBucket(price=105.0, notional_usd=1_000_000.0)],
    )


def _technical_snapshot() -> dict:
    return {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
        "atr": 2.0,
    }


@pytest.mark.asyncio
async def test_compute_decision_combines_all_three_scores_and_calls_llm():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = [{"side": "buy", "amount_usd": 300.0}]
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = _liquidation_snapshot()

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
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.symbol == "BTCUSDT"
    assert decision.whale_score == pytest.approx(1.0)  # all-buy volume_bias
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.liquidation_score == pytest.approx(1.0)
    assert decision.weighted_score == pytest.approx(0.60 * 1.0 + 0.25 * 0.475 + 0.15 * 1.0)
    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.reasoning == "Aligned signals."

    liquidation_storage.latest_snapshot.assert_called_once_with("BTCUSDT")
    mock_request_decision.assert_awaited_once()
    call_kwargs = mock_request_decision.call_args.kwargs
    # The single short cluster at 105 should show up as concrete entry/exit context,
    # not the "unavailable" placeholder used when there's no liquidation snapshot.
    assert "short_above=[(105.0, 1000000.0)]" in call_kwargs["user_message"]


@pytest.mark.asyncio
async def test_compute_decision_falls_back_to_two_signal_weighting_when_liquidation_missing():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = [{"side": "buy", "amount_usd": 300.0}]
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = None

    anthropic_client = MagicMock()

    with patch(
        "hello_coin.decision.service.request_decision",
        new=AsyncMock(
            return_value={"action": "buy", "confidence": 0.8, "reasoning": "Aligned signals."}
        ),
    ):
        decision = await compute_decision(
            symbol="BTCUSDT",
            timeframe="1h",
            whale_storage=whale_storage,
            technical_storage=technical_storage,
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.liquidation_score is None
    assert decision.weighted_score == pytest.approx(0.7 * 1.0 + 0.3 * 0.475)


@pytest.mark.asyncio
async def test_compute_decision_reports_missing_data_without_reweighting():
    whale_storage = MagicMock()
    whale_storage.recent_events.return_value = []
    whale_storage.recent_metrics.return_value = []

    technical_storage = MagicMock()
    technical_storage.latest_snapshot.return_value = _technical_snapshot()

    liquidation_storage = MagicMock()
    liquidation_storage.latest_snapshot.return_value = None

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
            liquidation_storage=liquidation_storage,
            anthropic_client=anthropic_client,
            model="claude-sonnet-5",
            whale_lookback_hours=24,
        )

    assert decision.whale_score is None
    assert decision.technical_score == pytest.approx(0.475)
    assert decision.weighted_score is None  # never re-weighted to 100% technical
