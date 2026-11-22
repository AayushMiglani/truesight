"""A short tool-calling loop. No framework."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from truesight.llm import LLM, Reply, ToolCall, llm_from_env
from truesight.tools import DEFAULT_TOOLS, Tool, to_openai_tools

SYSTEM_PROMPT = (
    "You are an incident investigator. "
    "Use tools when you need more information. "
    "When you are done, reply with a single JSON object and no other text. "
    "It must have exactly these keys: component, fault_type, root_cause, explanation."
)


@dataclass
class Answer:
    component: str
    fault_type: str
    root_cause: str
    explanation: str


class MaxStepsExceeded(Exception):
    """Raised when the model never returns a final answer."""


def investigate(
    alert: str,
    llm: LLM | None = None,
    tools: Sequence[Tool] | None = None,
    max_steps: int = 8,
) -> Answer:
    """Explain an alert.

    Each step is one model call. A tool that is missing or raises is reported
    back to the model as that call's tool result. Raises MaxStepsExceeded when
    the model is still calling tools after max_steps calls. The final text is
    parsed into an Answer; if it is not the expected JSON, the raw text is the
    explanation.
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
            return _parse_answer(reply.text or "")
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


def _parse_answer(text: str) -> Answer:
    try:
        data = json.loads(_json_body(text))
        keys = ("component", "fault_type", "root_cause", "explanation")
        if not isinstance(data, dict) or any(not isinstance(data.get(key), str) for key in keys):
            raise ValueError
        return Answer(
            component=data["component"],
            fault_type=data["fault_type"],
            root_cause=data["root_cause"],
            explanation=data["explanation"],
        )
    except (json.JSONDecodeError, ValueError):
        return Answer("", "", "", text)


def _json_body(text: str) -> str:
    """Return the first JSON object in text, ignoring prose and fences around it."""
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char == "{":
            try:
                _, end_idx = decoder.raw_decode(text, i)
                return text[i:end_idx]
            except json.JSONDecodeError:
                continue
    return text.strip()


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
