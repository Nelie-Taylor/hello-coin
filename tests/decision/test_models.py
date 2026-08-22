from datetime import UTC, datetime

from hello_coin.decision.models import Decision


def test_decision_holds_fields():
    decision = Decision(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
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
        timestamp=datetime(2026, 8, 22, tzinfo=UTC),
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
