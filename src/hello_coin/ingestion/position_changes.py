from hello_coin.ingestion.models import PositionChange, WhaleEvent

PositionKey = tuple[str, str]


class PositionChangeTracker:
    """Track active positions without treating unavailable reads as closes."""

    def __init__(self) -> None:
        self._baseline_ready = False
        self._positions: dict[PositionKey, WhaleEvent] = {}

    def record(
        self,
        observed: dict[PositionKey, WhaleEvent],
        confirmed: set[PositionKey],
    ) -> list[PositionChange]:
        if not self._baseline_ready:
            self._positions.update(observed)
            self._baseline_ready = True
            return []

        changes: list[PositionChange] = []
        for key, event in observed.items():
            if key not in self._positions:
                changes.append(PositionChange("open", event))
            self._positions[key] = event

        for key, event in list(self._positions.items()):
            if key in confirmed and key not in observed:
                changes.append(PositionChange("close", event))
                del self._positions[key]

        return changes
