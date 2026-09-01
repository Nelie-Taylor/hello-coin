from datetime import UTC, datetime

from hello_coin.decision.models import Decision
from hello_coin.decision.storage import DecisionStorage


def _decision(timestamp: datetime) -> Decision:
    return Decision(
        symbol="BTCUSDT",
        timestamp=timestamp,
        technical_score=0.475,
        liquidation_score=0.23,
        weighted_score=0.377,
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
