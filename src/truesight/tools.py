"""Tools the agent can call. echo is a stand-in until real incident tools exist."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    function: Callable[..., str]


def echo(text: str) -> str:
    return text


echo_tool = Tool(
    name="echo",
    description="Return the given text unchanged.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    function=echo,
)

DEFAULT_TOOLS: tuple[Tool, ...] = (echo_tool,)


def to_openai_tools(tools: Sequence[Tool]) -> list[dict]:
    """Shape tools the way chat.completions expects them."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
