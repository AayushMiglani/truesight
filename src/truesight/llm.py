"""The only module that talks to a model. DeepSeek speaks the OpenAI chat API."""

import json
import os
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
# Per attempt. The SDK default is 600 s, which with retries can stall one step for 30 min.
REQUEST_TIMEOUT_SECONDS = 180


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    # The raw text when the model's arguments were not valid JSON; arguments is then {}.
    invalid_arguments: str | None = None


@dataclass
class Reply:
    text: str | None = None
    tool_calls: list[ToolCall] | None = None
    # Thinking-mode chain of thought. DeepSeek needs it sent back on later requests
    # that carry tools, or the model loses its earlier reasoning.
    reasoning: str | None = None


class LLM(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> Reply: ...


class OpenAICompatibleLLM:
    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.model = model
        # Retry transient failures (timeouts, 5xx, 429) so one flaky request does not
        # end a whole investigation; the SDK backs off between tries.
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=2,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        kwargs: dict = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        message = self.client.chat.completions.create(**kwargs).choices[0].message
        reasoning = (message.model_extra or {}).get("reasoning_content") or None
        if not message.tool_calls:
            return Reply(text=message.content or "", reasoning=reasoning)
        calls = [_tool_call(call) for call in message.tool_calls]
        return Reply(text=message.content, tool_calls=calls, reasoning=reasoning)


def _tool_call(call) -> ToolCall:
    raw = call.function.arguments or "{}"
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        return ToolCall(id=call.id, name=call.function.name, arguments={}, invalid_arguments=raw)
    if not isinstance(arguments, dict):
        arguments = {}
    return ToolCall(id=call.id, name=call.function.name, arguments=arguments)


def llm_from_env() -> OpenAICompatibleLLM:
    # The key is read here, when a real client is built, not at import.
    api_key = os.environ.get("TRUESIGHT_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("TRUESIGHT_LLM_API_KEY is required")
    base_url = os.environ.get("TRUESIGHT_LLM_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("TRUESIGHT_LLM_MODEL", DEFAULT_MODEL)
    return OpenAICompatibleLLM(base_url=base_url, api_key=api_key, model=model)
