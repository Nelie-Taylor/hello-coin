import pytest

from hello_coin.dashboard.models import compute_market_bias


def test_market_bias_follows_technical_score():
    bias = compute_market_bias(technical_score=0.55)

    assert bias.score == pytest.approx(0.55)
    assert bias.label == "BULLISH BIAS"


@pytest.mark.parametrize(
    ("technical_score", "label"),
    [
        (0.0, "WAIT"),
        (-0.5, "BEARISH BIAS"),
        (None, "INSUFFICIENT DATA"),
    ],
)
def test_market_bias_labels_threshold_and_missing_input(
    technical_score: float | None, label: str
):
    bias = compute_market_bias(technical_score=technical_score)

    assert bias.label == label
