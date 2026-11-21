"""The only module that talks to a model. DeepSeek speaks the OpenAI chat API."""

import json
import os
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    text: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLM(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> Reply: ...


class OpenAICompatibleLLM:
    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.model = model
        # The SDK retries twice by default. This loop wants one request per step.
        self.client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        kwargs: dict = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        message = self.client.chat.completions.create(**kwargs).choices[0].message
        if not message.tool_calls:
            return Reply(text=message.content or "")
        calls = []
        for call in message.tool_calls:
            arguments = json.loads(call.function.arguments or "{}")
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        return Reply(text=message.content, tool_calls=calls)


def llm_from_env() -> OpenAICompatibleLLM:
    # The key is read here, when a real client is built, not at import.
    api_key = os.environ.get("TRUESIGHT_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("TRUESIGHT_LLM_API_KEY is required")
    base_url = os.environ.get("TRUESIGHT_LLM_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("TRUESIGHT_LLM_MODEL", DEFAULT_MODEL)
    return OpenAICompatibleLLM(base_url=base_url, api_key=api_key, model=model)
