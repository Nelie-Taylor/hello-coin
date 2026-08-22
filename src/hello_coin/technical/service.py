from hello_coin.technical.indicators import atr, bollinger_bands, ema, macd, rsi
from hello_coin.technical.klines import fetch_klines
from hello_coin.technical.models import IndicatorSnapshot

DEFAULT_CANDLE_LIMIT = 100
EMA_PERIOD = 20
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BOLLINGER_PERIOD = 20
ATR_PERIOD = 14


async def compute_snapshot(symbol: str, timeframe: str) -> IndicatorSnapshot:
    candles = await fetch_klines(symbol, timeframe, DEFAULT_CANDLE_LIMIT)
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    macd_line, macd_signal, macd_histogram = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    bb_upper, bb_middle, bb_lower = bollinger_bands(closes, BOLLINGER_PERIOD, 2.0)
    latest = candles[-1]

    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=latest.open_time,
        close_price=latest.close,
        rsi=rsi(closes, RSI_PERIOD),
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_histogram=macd_histogram,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        ema=ema(closes, EMA_PERIOD),
        atr=atr(highs, lows, closes, ATR_PERIOD),
        raw={"candle_count": len(candles)},
    )
