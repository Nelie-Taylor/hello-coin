from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hello_coin.decision.llm import DECIDE_TOOL, request_decision


def _tool_use_response(input_payload: dict):
    block = SimpleNamespace(type="tool_use", name="decide", input=input_payload)
    return SimpleNamespace(content=[block])


def _text_only_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


@pytest.mark.asyncio
async def test_request_decision_returns_tool_input():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_tool_use_response(
            {"action": "buy", "confidence": 0.8, "reasoning": "Whale accumulation."}
        )
    )

    result = await request_decision(
        mock_client, model="claude-sonnet-5", system="system prompt", user_message="user prompt"
    )

    assert result == {"action": "buy", "confidence": 0.8, "reasoning": "Whale accumulation."}
    mock_client.messages.create.assert_awaited_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert call_kwargs["system"] == "system prompt"
    assert call_kwargs["messages"] == [{"role": "user", "content": "user prompt"}]
    assert call_kwargs["tools"] == [DECIDE_TOOL]
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "decide"}


@pytest.mark.asyncio
async def test_request_decision_raises_when_no_tool_use_block():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_text_only_response("I refuse."))

    with pytest.raises(RuntimeError, match="did not include a decide tool call"):
        await request_decision(
            mock_client, model="claude-sonnet-5", system="system prompt", user_message="user prompt"
        )
