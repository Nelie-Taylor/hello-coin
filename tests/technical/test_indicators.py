import pytest

from hello_coin.technical.indicators import atr, bollinger_bands, ema, macd, rsi


def test_ema_matches_reference_value():
    # Reference calculation: seed = SMA(1,2,3) = 2.0; then EMA(4) = (4-2)*0.5+2 = 3.0;
    # EMA(5) = (5-3)*0.5+3 = 4.0. k = 2/(period+1) = 0.5 for period=3.
    result = ema([1, 2, 3, 4, 5], period=3)
    assert result == pytest.approx(4.0)


def test_ema_returns_none_with_insufficient_data():
    assert ema([1, 2], period=3) is None


def test_rsi_matches_reference_value():
    # Reference calculation (Wilder's smoothing, period=3):
    # diffs from [10,12,11,13,12,14] = [+2,-1,+2,-1,+2]
    # seed avg_gain = (2+0+2)/3 = 4/3, seed avg_loss = (0+1+0)/3 = 1/3
    # step (gain=0,loss=1): avg_gain=(4/3*2+0)/3=8/9, avg_loss=(1/3*2+1)/3=5/9
    # step (gain=2,loss=0): avg_gain=(8/9*2+2)/3=34/27, avg_loss=(5/9*2+0)/3=10/27
    # RS = 34/10 = 3.4; RSI = 100 - 100/(1+3.4) = 850/11 = 77.27272727272727
    result = rsi([10, 12, 11, 13, 12, 14], period=3)
    assert result == pytest.approx(850 / 11)


def test_rsi_returns_none_with_insufficient_data():
    assert rsi([10, 12], period=3) is None


def test_rsi_is_100_when_no_losses():
    result = rsi([10, 11, 12, 13], period=3)
    assert result == pytest.approx(100.0)


def test_macd_matches_reference_value():
    # Reference calculation (fast=3, slow=6, signal=2) on a pure linear series
    # [1..14]: the fast/slow EMA gap converges to a constant (1.5) once both EMAs
    # are past their warm-up window, and the signal EMA of a constant series equals
    # that same constant — so histogram converges to 0.0. Computed via a standalone
    # reference script implementing the same seeded-EMA algorithm; see the plan.
    closes = list(range(1, 15))
    macd_line, signal_line, histogram = macd(closes, fast=3, slow=6, signal=2)
    assert macd_line == pytest.approx(1.5)
    assert signal_line == pytest.approx(1.5)
    assert histogram == pytest.approx(0.0, abs=1e-9)


def test_macd_returns_none_triple_with_insufficient_data():
    macd_line, signal_line, histogram = macd([1, 2, 3], fast=3, slow=6, signal=2)
    assert macd_line is None
    assert signal_line is None
    assert histogram is None


def test_bollinger_bands_matches_reference_value():
    # Reference calculation (period=5, num_std=2) on window [15,16,17,18,19]:
    # mean=17.0; population variance = ((-2)^2+(-1)^2+0+1^2+2^2)/5 = 10/5 = 2.0
    # std = sqrt(2) = 1.4142135623730951
    # upper = 17 + 2*std = 19.82842712474619; lower = 17 - 2*std = 14.17157287525381
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    upper, middle, lower = bollinger_bands(closes, period=5, num_std=2.0)
    assert upper == pytest.approx(19.82842712474619)
    assert middle == pytest.approx(17.0)
    assert lower == pytest.approx(14.17157287525381)


def test_bollinger_bands_returns_none_triple_with_insufficient_data():
    upper, middle, lower = bollinger_bands([1, 2], period=5, num_std=2.0)
    assert upper is None
    assert middle is None
    assert lower is None


def test_atr_matches_reference_value():
    # Reference calculation (Wilder's smoothing, period=3):
    # True ranges from highs/lows/closes below: [3, 2, 3, 3, 3, 4]
    # seed avg_tr = (3+2+3)/3 = 8/3
    # step tr=3: avg_tr=(8/3*2+3)/3=25/9=2.777...
    # step tr=3: avg_tr=(25/9*2+3)/3=77/27=2.851851...
    # step tr=4: avg_tr=(77/27*2+4)/3=262/81=3.2345679012345676
    highs = [10, 12, 11, 13, 15, 14, 16]
    lows = [8, 9, 9, 10, 12, 11, 13]
    closes = [9, 11, 10, 12, 14, 12, 15]
    result = atr(highs, lows, closes, period=3)
    assert result == pytest.approx(3.2345679012345676)


def test_atr_returns_none_with_insufficient_data():
    assert atr([10, 11], [9, 10], [9, 10], period=3) is None
