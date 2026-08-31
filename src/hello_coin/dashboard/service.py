import json
from collections.abc import Sequence
from datetime import datetime, timedelta

from hello_coin.dashboard.models import (
    CoinPositionTable,
    DashboardSnapshot,
    SourceStatus,
    compute_market_bias,
)
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
        hyperdash_watch_coins: Sequence[str] = (),
        position_freshness_seconds: int | None = None,
    ) -> None:
        self._whale_storage = whale_storage
        self._technical_storage = technical_storage
        self._timeframe = timeframe
        self._lookback_hours = lookback_hours
        self._hyperdash_watch_coins = tuple(coin.upper() for coin in hyperdash_watch_coins)
        self._position_freshness_seconds = position_freshness_seconds

    def close(self) -> None:
        self._whale_storage.close()
        self._technical_storage.close()

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
        coin_positions = self._load_coin_positions(sources, now)
        activity_symbols = list(dict.fromkeys([asset, *self._hyperdash_watch_coins]))
        # 30 days matches the skew charts' lookback window, for a consistent dashboard feel.
        price_since = now - timedelta(days=30)
        price_history = tuple(
            self._technical_storage.recent_snapshots(symbol, self._timeframe, price_since)
        )
        return DashboardSnapshot(
            symbol=symbol,
            technical=technical,
            whale_events=tuple(self._whale_storage.latest_events(activity_symbols, limit=20)),
            bias=bias,
            source_statuses=tuple(self._source_status(source, now) for source in sources),
            refreshed_at=now,
            coin_positions=coin_positions,
            price_history=price_history,
        )

    def _load_coin_positions(
        self, sources: Sequence[Adapter], now: datetime
    ) -> tuple[CoinPositionTable, ...]:
        if not self._hyperdash_watch_coins:
            return ()
        hyperdash = next((source for source in sources if source.name == "hyperdash"), None)
        freshness = self._position_freshness_seconds
        if freshness is None:
            freshness = min((hyperdash.poll_interval_seconds * 2 if hyperdash else 120), 300)
        since = now - timedelta(seconds=freshness)
        # 30 days matches WhaleStorage.insert_skew_snapshots's own pruning window.
        skew_since = now - timedelta(days=30)
        tables: list[CoinPositionTable] = []
        for coin in self._hyperdash_watch_coins:
            rows: list[dict] = []
            for row in self._whale_storage.recent_events(coin, since):
                if row["source"] != "hyperdash" or row["event_type"] != "position":
                    continue
                try:
                    row["raw"] = json.loads(row["raw"])
                except (TypeError, json.JSONDecodeError):
                    row["raw"] = {}
                rows.append(row)
            rows.sort(key=lambda row: row["amount_usd"] or 0, reverse=True)
            status = self._coin_status(coin, hyperdash, now, bool(rows))
            skew_history = tuple(self._whale_storage.recent_skew_history(coin, skew_since))
            tables.append(
                CoinPositionTable(
                    coin=coin, rows=tuple(rows), status=status, skew_history=skew_history
                )
            )
        return tuple(tables)

    @staticmethod
    def _coin_status(
        coin: str, hyperdash: Adapter | None, now: datetime, has_rows: bool
    ) -> SourceStatus:
        if hyperdash is None:
            return SourceStatus("hyperdash", "NOT CONFIGURED", None, "Hyperdash adapter unavailable")
        raw_status = getattr(hyperdash, "coin_statuses", {}).get(coin, {})
        state = raw_status.get("state")
        detail = raw_status.get("detail")
        last_success = raw_status.get("last_success_at")
        if state in {"ERROR", "NOT CONFIGURED"}:
            return SourceStatus("hyperdash", state, last_success, str(detail or state))
        if has_rows:
            return SourceStatus("hyperdash", "LIVE", last_success or now, str(detail or "current position(s)"))
        return SourceStatus("hyperdash", "STALE", last_success, str(detail or "no fresh positions"))

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
