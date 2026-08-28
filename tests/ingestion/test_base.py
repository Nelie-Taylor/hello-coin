import pytest

from hello_coin.ingestion.adapters.base import Adapter


class _AlwaysSucceedsAdapter(Adapter):
    name = "always_succeeds"
    poll_interval_seconds = 1

    async def fetch(self):
        return []


class _CountingFailingAdapter(Adapter):
    name = "counting_failing"
    poll_interval_seconds = 1
    max_consecutive_failures = 3

    def __init__(self):
        super().__init__()
        self.fetch_calls = 0

    async def fetch(self):
        self.fetch_calls += 1
        raise RuntimeError("boom")


class _FlakyAdapter(Adapter):
    name = "flaky"
    poll_interval_seconds = 1

    def __init__(self):
        super().__init__()
        self._should_fail = True

    async def fetch(self):
        if self._should_fail:
            self._should_fail = False
            raise RuntimeError("offline")
        return []


@pytest.mark.asyncio
async def test_safe_fetch_returns_result_on_success():
    adapter = _AlwaysSucceedsAdapter()

    result = await adapter.safe_fetch()

    assert result == []
    assert adapter.disabled is False


@pytest.mark.asyncio
async def test_safe_fetch_disables_after_max_consecutive_failures():
    adapter = _CountingFailingAdapter()

    for _ in range(3):
        result = await adapter.safe_fetch()
        assert result == []

    assert adapter.disabled is True
    assert adapter.fetch_calls == 3

    await adapter.safe_fetch()
    assert adapter.fetch_calls == 3  # fetch() is not called again once disabled


@pytest.mark.asyncio
async def test_safe_fetch_records_success_and_clears_previous_error():
    adapter = _FlakyAdapter()

    await adapter.safe_fetch()

    assert adapter.last_success_at is None
    assert adapter.last_error == "offline"

    await adapter.safe_fetch()

    assert adapter.last_success_at is not None
    assert adapter.last_error is None


def test_is_configured_defaults_to_true():
    adapter = _AlwaysSucceedsAdapter()
    assert adapter.is_configured() is True
