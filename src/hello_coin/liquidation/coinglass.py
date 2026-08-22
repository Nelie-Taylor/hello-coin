import httpx

from hello_coin.ingestion.config import Settings

COINGLASS_HEATMAP_URL = "https://open-api-v4.coinglass.com/api/futures/liquidation-heatmap"


def is_configured(settings: Settings) -> bool:
    return bool(settings.coinglass_api_key)


async def fetch_heatmap(symbol: str, api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            COINGLASS_HEATMAP_URL,
            params={"symbol": symbol},
            headers={"CG-API-KEY": api_key},
        )
        response.raise_for_status()
        return response.json()
