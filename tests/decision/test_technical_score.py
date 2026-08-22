import pytest

from hello_coin.decision.technical_score import compute_technical_score


def test_compute_technical_score_combines_all_four_signals():
    # Reference calculation:
    # score_rsi(30) = (50-30)/50 = 0.4
    # score_macd(5) = 1.0 (positive histogram)
    # score_bb(close=105, upper=110, middle=100) = (100-105)/(110-100) = -0.5
    # score_ema(close=105, ema=100) = 1.0 (close above EMA)
    # technical_score = mean[0.4, 1.0, -0.5, 1.0] = 0.475
    snapshot = {
        "rsi": 30,
        "macd_histogram": 5,
        "close_price": 105,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": 100,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(0.475)


def test_score_rsi_clips_and_flips_sign_for_overbought():
    # Reference: score_rsi(70) = (50-70)/50 = -0.4 (overbought -> bearish/negative)
    snapshot = {
        "rsi": 70,
        "macd_histogram": None,
        "close_price": None,
        "bb_upper": None,
        "bb_middle": None,
        "ema": None,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(-0.4)


def test_bollinger_score_clips_when_price_beyond_upper_band():
    # Reference: raw (100-115)/(110-100) = -1.5, clipped to -1.0
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": 115,
        "bb_upper": 110,
        "bb_middle": 100,
        "ema": None,
    }
    result = compute_technical_score(snapshot)
    assert result == pytest.approx(-1.0)


def test_compute_technical_score_is_none_when_all_fields_missing():
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": None,
        "bb_upper": None,
        "bb_middle": None,
        "ema": None,
    }
    assert compute_technical_score(snapshot) is None


def test_bollinger_score_is_excluded_when_bands_are_degenerate():
    # bb_upper == bb_middle (zero standard deviation) would divide by zero — excluded, not crashed.
    snapshot = {
        "rsi": None,
        "macd_histogram": None,
        "close_price": 100,
        "bb_upper": 100,
        "bb_middle": 100,
        "ema": None,
    }
    assert compute_technical_score(snapshot) is None
