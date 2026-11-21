"""A short tool-calling loop. No framework."""

import json
from collections.abc import Sequence

from truesight.llm import LLM, Reply, ToolCall, llm_from_env
from truesight.tools import DEFAULT_TOOLS, Tool, to_openai_tools

SYSTEM_PROMPT = (
    "You are an incident investigator. "
    "Explain the likely root cause of the alert. "
    "Use tools when you need more information."
)


class MaxStepsExceeded(Exception):
    """Raised when the model never returns a final answer."""


def investigate(
    alert: str,
    llm: LLM | None = None,
    tools: Sequence[Tool] | None = None,
    max_steps: int = 8,
) -> str:
    """Explain an alert.

    Each step is one model call. A tool that is missing or raises is reported
    back to the model as that call's tool result. Raises MaxStepsExceeded when
    the model is still calling tools after max_steps calls.
    """
    if llm is None:
        llm = llm_from_env()
    chosen = DEFAULT_TOOLS if tools is None else tools
    by_name = {tool.name: tool for tool in chosen}
    openai_tools = to_openai_tools(chosen)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": alert},
    ]

    for _ in range(max_steps):
        reply = llm.complete(messages, openai_tools)
        if not reply.tool_calls:
            return reply.text or ""
        messages.append(_assistant_message(reply))
        for call in reply.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _run_tool(by_name, call),
                }
            )

    raise MaxStepsExceeded(f"no final answer after {max_steps} steps")


def _assistant_message(reply: Reply) -> dict:
    calls = reply.tool_calls or []
    return {
        "role": "assistant",
        "content": reply.text,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in calls
        ],
    }


def _run_tool(by_name: dict[str, Tool], call: ToolCall) -> str:
    tool = by_name.get(call.name)
    if tool is None:
        return f"error: unknown tool {call.name}"
    try:
        return str(tool.function(**call.arguments))
    except Exception as exc:
        return f"error: {exc}"
