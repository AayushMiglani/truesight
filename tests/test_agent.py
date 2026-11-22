import json

import pytest

from truesight.__main__ import main
from truesight.agent import Answer, MaxStepsExceeded, investigate
from truesight.llm import Reply, ToolCall
from truesight.tools import Tool, echo_tool

ANSWER = {
    "component": "disk",
    "fault_type": "full",
    "root_cause": "logs",
    "explanation": "disk filled up",
}


class FakeLLM:
    """Scripted model. Records each complete() call and takes no network."""

    def __init__(self, replies: list[Reply]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append((list(messages), tools))
        return self._replies.pop(0)


def test_model_answers_immediately():
    llm = FakeLLM([Reply(text=json.dumps(ANSWER))])
    assert investigate("disk 95%", llm=llm) == Answer(**ANSWER)
    messages, tools = llm.calls[0]
    assert "incident investigator" in messages[0]["content"]
    assert "fault_type" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "disk 95%"}
    assert tools[0]["function"]["name"] == "echo"
    assert len(llm.calls) == 1


def test_echo_result_is_fed_back_then_answered():
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "echo", {"text": "ping"})]),
            Reply(text=json.dumps(ANSWER)),
        ]
    )
    assert investigate("check echo", llm=llm, tools=[echo_tool]) == Answer(**ANSWER)
    assert [m["role"] for m in llm.calls[0][0]] == ["system", "user"]
    messages = llm.calls[1][0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert json.loads(messages[2]["tool_calls"][0]["function"]["arguments"]) == {"text": "ping"}
    assert messages[3] == {"role": "tool", "tool_call_id": "call-1", "content": "ping"}


def test_unknown_tool_error_is_fed_back():
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "missing", {})]),
            Reply(text=json.dumps(ANSWER)),
        ]
    )
    assert investigate("alert", llm=llm) == Answer(**ANSWER)
    assert llm.calls[1][0][-1]["content"] == "error: unknown tool missing"


def test_tool_exception_is_fed_back():
    def boom(text: str) -> str:
        raise RuntimeError(f"failed on {text}")

    broken = Tool("boom", "Always fails.", {"type": "object"}, boom)
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "boom", {"text": "x"})]),
            Reply(text=json.dumps(ANSWER)),
        ]
    )
    assert investigate("alert", llm=llm, tools=[broken]) == Answer(**ANSWER)
    assert llm.calls[1][0][-1]["content"] == "error: failed on x"


def test_max_steps_raises_when_the_model_never_answers():
    replies = [Reply(tool_calls=[ToolCall(f"call-{i}", "echo", {"text": "x"})]) for i in range(4)]
    llm = FakeLLM(replies)
    with pytest.raises(MaxStepsExceeded, match="no final answer after 3 steps"):
        investigate("alert", llm=llm, tools=[echo_tool], max_steps=3)
    assert len(llm.calls) == 3


def test_parses_plain_json():
    llm = FakeLLM([Reply(text=json.dumps(ANSWER))])
    assert investigate("alert", llm=llm, tools=[]) == Answer(**ANSWER)


def test_parses_fenced_json():
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    llm = FakeLLM([Reply(text=fenced)])
    assert investigate("alert", llm=llm, tools=[]) == Answer(**ANSWER)


def test_parses_json_surrounded_by_prose():
    text = "Here's my answer: " + json.dumps(ANSWER) + " Hope that helps."
    llm = FakeLLM([Reply(text=text)])
    assert investigate("alert", llm=llm, tools=[]) == Answer(**ANSWER)


def test_malformed_json_keeps_the_raw_text():
    llm = FakeLLM([Reply(text="not json")])
    assert investigate("alert", llm=llm, tools=[]) == Answer("", "", "", "not json")


def test_incomplete_json_keeps_the_raw_text():
    raw = '{"component": "disk"}'
    llm = FakeLLM([Reply(text=raw)])
    assert investigate("alert", llm=llm, tools=[]) == Answer("", "", "", raw)


def test_main_prints_the_investigation(monkeypatch, capsys):
    monkeypatch.setattr(
        "truesight.__main__.investigate",
        lambda alert: Answer("disk", "full", "logs", f"cause: {alert}"),
    )
    main(["truesight", "disk", "full"])
    assert json.loads(capsys.readouterr().out) == {
        "component": "disk",
        "fault_type": "full",
        "root_cause": "logs",
        "explanation": "cause: disk full",
    }


def test_main_loads_tools_from_mcp_url(monkeypatch, capsys):
    seen = {}

    def fake_tools(url: str):
        seen["url"] = url
        return [echo_tool]

    def fake_investigate(alert: str, tools=None):
        seen["alert"] = alert
        seen["tool"] = tools[0].name
        return Answer("disk", "full", "logs", "explained")

    monkeypatch.setattr("truesight.__main__.tools_from_mcp", fake_tools)
    monkeypatch.setattr("truesight.__main__.investigate", fake_investigate)
    main(["truesight", "--mcp-url", "http://127.0.0.1:9/mcp", "disk", "full"])
    assert seen == {
        "url": "http://127.0.0.1:9/mcp",
        "alert": "disk full",
        "tool": "echo",
    }
    assert json.loads(capsys.readouterr().out)["explanation"] == "explained"
