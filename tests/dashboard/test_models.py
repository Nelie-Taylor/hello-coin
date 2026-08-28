import pytest

from hello_coin.dashboard.models import compute_market_bias


def test_market_bias_uses_approved_70_30_weights():
    bias = compute_market_bias(whale_score=1.0, technical_score=-0.5)

    assert bias.score == pytest.approx(0.55)
    assert bias.label == "BULLISH BIAS"


@pytest.mark.parametrize(
    ("whale_score", "technical_score", "label"),
    [
        (0.0, 0.0, "WAIT"),
        (-0.5, -0.5, "BEARISH BIAS"),
        (None, 0.8, "INSUFFICIENT DATA"),
        (0.8, None, "INSUFFICIENT DATA"),
    ],
)
def test_market_bias_labels_threshold_and_missing_input(
    whale_score: float | None, technical_score: float | None, label: str
):
    bias = compute_market_bias(whale_score=whale_score, technical_score=technical_score)

    assert bias.label == label
