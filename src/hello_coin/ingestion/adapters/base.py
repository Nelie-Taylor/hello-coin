import logging
from abc import ABC, abstractmethod

from hello_coin.ingestion.models import WhaleEvent, WhaleMetric

logger = logging.getLogger(__name__)


class Adapter(ABC):
    """Base class for a single whale data source.

    Subclasses implement `fetch()` only. Scheduling, storage, and disabling a
    persistently-failing source are handled here so every adapter behaves the
    same way under errors.
    """

    name: str
    poll_interval_seconds: int
    max_consecutive_failures: int = 5

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._disabled = False

    def is_configured(self) -> bool:
        return True

    @property
    def disabled(self) -> bool:
        return self._disabled

    @abstractmethod
    async def fetch(self) -> list[WhaleEvent] | list[WhaleMetric]:
        raise NotImplementedError

    async def safe_fetch(self) -> list[WhaleEvent] | list[WhaleMetric]:
        if self._disabled:
            return []
        try:
            result = await self.fetch()
        except Exception:
            logger.exception("%s: fetch failed", self.name)
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.max_consecutive_failures:
                self._disabled = True
                logger.error(
                    "%s: disabled after %d consecutive failures",
                    self.name,
                    self._consecutive_failures,
                )
            return []
        self._consecutive_failures = 0
        return result
