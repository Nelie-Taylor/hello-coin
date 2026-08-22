from datetime import UTC, datetime

import httpx

from hello_coin.technical.models import Candle

BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


async def fetch_klines(symbol: str, interval: str, limit: int) -> list[Candle]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        rows = response.json()
        return [
            Candle(
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
