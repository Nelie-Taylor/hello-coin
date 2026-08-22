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
