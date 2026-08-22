from typing import Any

DECIDE_TOOL = {
    "name": "decide",
    "description": "Record a trading decision (action, confidence, reasoning) for a crypto symbol.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
        },
        "required": ["action", "confidence", "reasoning"],
    },
}


async def request_decision(
    client: Any, model: str, system: str, user_message: str
) -> dict[str, Any]:
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        tools=[DECIDE_TOOL],
        tool_choice={"type": "tool", "name": "decide"},
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Anthropic response did not include a decide tool call")
