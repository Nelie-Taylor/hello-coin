from datetime import UTC, datetime

from hello_coin.decision.models import Decision


def test_decision_holds_fields():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        technical_score=0.475,
        liquidation_score=0.23,
        weighted_score=0.377,
        action="buy",
        confidence=0.8,
        reasoning="Bullish momentum with short liquidations overhead.",
        raw={"model": "claude-sonnet-5"},
    )

    assert decision.action == "buy"
    assert decision.confidence == 0.8
    assert decision.liquidation_score == 0.23
    assert decision.raw == {"model": "claude-sonnet-5"}


def test_decision_allows_none_scores():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
        technical_score=None,
        liquidation_score=None,
        weighted_score=None,
        action="hold",
        confidence=0.4,
        reasoning="No technical data available this cycle.",
        raw={},
    )

    assert decision.technical_score is None
    assert decision.liquidation_score is None
    assert decision.weighted_score is None
