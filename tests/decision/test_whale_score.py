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
