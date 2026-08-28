from collections.abc import Sequence
from datetime import datetime, timedelta

from hello_coin.dashboard.models import DashboardSnapshot, SourceStatus, compute_market_bias
from hello_coin.decision.technical_score import compute_technical_score
from hello_coin.decision.whale_score import base_asset, compute_whale_score
from hello_coin.ingestion.adapters.base import Adapter
from hello_coin.ingestion.storage import WhaleStorage
from hello_coin.technical.storage import TechnicalStorage


class DashboardService:
    def __init__(
        self,
        whale_storage: WhaleStorage,
        technical_storage: TechnicalStorage,
        *,
        timeframe: str,
        lookback_hours: int,
    ) -> None:
        self._whale_storage = whale_storage
        self._technical_storage = technical_storage
        self._timeframe = timeframe
        self._lookback_hours = lookback_hours

    def load_snapshot(
        self, symbol: str, sources: Sequence[Adapter], now: datetime
    ) -> DashboardSnapshot:
        asset = base_asset(symbol)
        since = now - timedelta(hours=self._lookback_hours)
        events = self._whale_storage.recent_events(asset, since)
        metrics = self._whale_storage.recent_metrics(symbol, since)
        metrics += self._whale_storage.recent_metrics(asset, since)
        technical = self._technical_storage.latest_snapshot(symbol, self._timeframe)
        technical_score = compute_technical_score(technical) if technical is not None else None
        bias = compute_market_bias(compute_whale_score(events, metrics), technical_score)
        return DashboardSnapshot(
            symbol=symbol,
            technical=technical,
            whale_events=tuple(self._whale_storage.latest_events(asset)),
            bias=bias,
            source_statuses=tuple(self._source_status(source, now) for source in sources),
            refreshed_at=now,
        )

    @staticmethod
    def _source_status(source: Adapter, now: datetime) -> SourceStatus:
        if source.disabled:
            return SourceStatus(
                name=source.name,
                state="ERROR",
                last_success_at=source.last_success_at,
                detail="source disabled after repeated failures",
            )
        if source.last_error is not None:
            return SourceStatus(
                name=source.name,
                state="ERROR",
                last_success_at=source.last_success_at,
                detail=source.last_error,
            )
        if source.last_success_at is None:
            return SourceStatus(
                name=source.name,
                state="STALE",
                last_success_at=None,
                detail="no successful poll",
            )
        maximum_age = timedelta(seconds=source.poll_interval_seconds * 2)
        if now - source.last_success_at > maximum_age:
            return SourceStatus(
                name=source.name,
                state="STALE",
                last_success_at=source.last_success_at,
                detail=source.last_success_at.isoformat(),
            )
        return SourceStatus(
            name=source.name,
            state="LIVE",
            last_success_at=source.last_success_at,
            detail=source.last_success_at.isoformat(),
        )
