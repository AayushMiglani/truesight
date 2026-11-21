import json

import pytest

from truesight.__main__ import main
from truesight.agent import MaxStepsExceeded, investigate
from truesight.llm import Reply, ToolCall
from truesight.tools import Tool, echo_tool


class FakeLLM:
    """Scripted model. Records each complete() call and takes no network."""

    def __init__(self, replies: list[Reply]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append((list(messages), tools))
        return self._replies.pop(0)


def test_model_answers_immediately():
    llm = FakeLLM([Reply(text="disk filled up")])
    assert investigate("disk 95%", llm=llm) == "disk filled up"
    messages, tools = llm.calls[0]
    assert "incident investigator" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "disk 95%"}
    assert tools[0]["function"]["name"] == "echo"
    assert len(llm.calls) == 1


def test_echo_result_is_fed_back_then_answered():
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "echo", {"text": "ping"})]),
            Reply(text="echo returned ping"),
        ]
    )
    assert investigate("check echo", llm=llm, tools=[echo_tool]) == "echo returned ping"
    assert [m["role"] for m in llm.calls[0][0]] == ["system", "user"]
    messages = llm.calls[1][0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert json.loads(messages[2]["tool_calls"][0]["function"]["arguments"]) == {"text": "ping"}
    assert messages[3] == {"role": "tool", "tool_call_id": "call-1", "content": "ping"}


def test_unknown_tool_error_is_fed_back():
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "missing", {})]),
            Reply(text="that tool does not exist"),
        ]
    )
    assert investigate("alert", llm=llm) == "that tool does not exist"
    assert llm.calls[1][0][-1]["content"] == "error: unknown tool missing"


def test_tool_exception_is_fed_back():
    def boom(text: str) -> str:
        raise RuntimeError(f"failed on {text}")

    broken = Tool("boom", "Always fails.", {"type": "object"}, boom)
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "boom", {"text": "x"})]),
            Reply(text="continued after the error"),
        ]
    )
    assert investigate("alert", llm=llm, tools=[broken]) == "continued after the error"
    assert llm.calls[1][0][-1]["content"] == "error: failed on x"


def test_max_steps_raises_when_the_model_never_answers():
    replies = [Reply(tool_calls=[ToolCall(f"call-{i}", "echo", {"text": "x"})]) for i in range(4)]
    llm = FakeLLM(replies)
    with pytest.raises(MaxStepsExceeded, match="no final answer after 3 steps"):
        investigate("alert", llm=llm, tools=[echo_tool], max_steps=3)
    assert len(llm.calls) == 3


def test_main_prints_the_investigation(monkeypatch, capsys):
    monkeypatch.setattr("truesight.__main__.investigate", lambda alert: f"cause: {alert}")
    main(["truesight", "disk", "full"])
    assert capsys.readouterr().out == "cause: disk full\n"
