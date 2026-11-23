import json

import pytest

from truesight.__main__ import main
from truesight.agent import SYSTEM_PROMPT, MaxStepsExceeded, investigate
from truesight.answer import parse_answer
from truesight.llm import Reply, ToolCall
from truesight.tools import Tool, echo_tool

ARGS = {
    "status": "established",
    "summary": "disk filled by logs",
    "component": "disk",
    "fault_type": "full",
    "location": {"kind": "resource", "address": "/var/log on db-1"},
    "mechanism": "log rotation stopped, disk filled",
    "evidence": [{"tool": "echo", "finding": "95%"}],
    "ruled_out": [],
}
ANSWER = parse_answer(ARGS)


def submit(call_id="final", args=ARGS):
    return Reply(tool_calls=[ToolCall(call_id, "submit_answer", args)])


class FakeLLM:
    """Scripted model. Records each complete() call and takes no network."""

    def __init__(self, replies: list[Reply]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append((list(messages), tools))
        return self._replies.pop(0)


def tool_names(tools: list[dict]) -> list[str]:
    return [t["function"]["name"] for t in tools]


def test_model_submits_immediately():
    llm = FakeLLM([submit()])
    assert investigate("disk 95%", llm=llm) == ANSWER
    messages, tools = llm.calls[0]
    assert "incident" in messages[0]["content"]
    assert "submit_answer" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "disk 95%"}
    assert tool_names(tools) == ["echo", "submit_answer"]
    assert len(llm.calls) == 1


def test_echo_result_is_fed_back_then_submitted():
    llm = FakeLLM([Reply(tool_calls=[ToolCall("call-1", "echo", {"text": "ping"})]), submit()])
    assert investigate("check echo", llm=llm, tools=[echo_tool]) == ANSWER
    messages = llm.calls[1][0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert json.loads(messages[2]["tool_calls"][0]["function"]["arguments"]) == {"text": "ping"}
    assert messages[3] == {"role": "tool", "tool_call_id": "call-1", "content": "ping"}


def test_reasoning_is_sent_back_with_the_tool_call():
    first = Reply(tool_calls=[ToolCall("call-1", "echo", {"text": "x"})], reasoning="plan: echo")
    llm = FakeLLM([first, submit()])
    investigate("alert", llm=llm, tools=[echo_tool])
    assert llm.calls[1][0][2]["reasoning_content"] == "plan: echo"


def test_no_reasoning_key_when_the_model_gave_none():
    llm = FakeLLM([Reply(tool_calls=[ToolCall("call-1", "echo", {"text": "x"})]), submit()])
    investigate("alert", llm=llm, tools=[echo_tool])
    assert "reasoning_content" not in llm.calls[1][0][2]


def test_unknown_tool_error_is_fed_back():
    llm = FakeLLM([Reply(tool_calls=[ToolCall("call-1", "missing", {})]), submit()])
    assert investigate("alert", llm=llm) == ANSWER
    assert llm.calls[1][0][-1]["content"] == "error: unknown tool missing"


def test_tool_exception_is_fed_back():
    def boom(text: str) -> str:
        raise RuntimeError(f"failed on {text}")

    broken = Tool("boom", "Always fails.", {"type": "object"}, boom)
    llm = FakeLLM([Reply(tool_calls=[ToolCall("call-1", "boom", {"text": "x"})]), submit()])
    assert investigate("alert", llm=llm, tools=[broken]) == ANSWER
    assert llm.calls[1][0][-1]["content"] == "error: failed on x"


def test_invalid_submission_is_fed_back_with_the_field():
    bad = {**ARGS, "status": "maybe"}
    llm = FakeLLM([submit("bad", bad), submit()])
    assert investigate("alert", llm=llm, tools=[]) == ANSWER
    last = llm.calls[1][0][-1]
    assert last["role"] == "tool"
    assert last["tool_call_id"] == "bad"
    assert last["content"].startswith("error: invalid answer: status:")


def test_text_reply_is_nudged_to_submit():
    llm = FakeLLM([Reply(text="It is the disk.", reasoning="hm"), submit()])
    assert investigate("alert", llm=llm, tools=[]) == ANSWER
    messages = llm.calls[1][0]
    assert messages[-2] == {
        "role": "assistant",
        "content": "It is the disk.",
        "reasoning_content": "hm",
    }
    assert messages[-1]["role"] == "user"
    assert "submit_answer" in messages[-1]["content"]


def test_out_of_steps_offers_only_submit_answer():
    calls = [Reply(tool_calls=[ToolCall(f"call-{i}", "echo", {"text": "x"})]) for i in range(3)]
    llm = FakeLLM([*calls, submit()])
    assert investigate("alert", llm=llm, tools=[echo_tool], max_steps=3) == ANSWER
    assert len(llm.calls) == 4
    messages, tools = llm.calls[3]
    assert tool_names(tools) == ["submit_answer"]
    assert messages[-1]["role"] == "user"
    assert "budget" in messages[-1]["content"]


def test_max_steps_raises_when_the_last_chance_is_not_a_valid_submission():
    calls = [Reply(tool_calls=[ToolCall(f"call-{i}", "echo", {"text": "x"})]) for i in range(4)]
    llm = FakeLLM(calls)
    with pytest.raises(MaxStepsExceeded, match="no final answer after 3 steps"):
        investigate("alert", llm=llm, tools=[echo_tool], max_steps=3)
    assert len(llm.calls) == 4


def test_submit_batched_with_other_calls_is_sent_back():
    batch = Reply(
        tool_calls=[
            ToolCall("call-1", "echo", {"text": "x"}),
            ToolCall("early", "submit_answer", ARGS),
        ]
    )
    llm = FakeLLM([batch, submit()])
    assert investigate("alert", llm=llm, tools=[echo_tool]) == ANSWER
    results = {m["tool_call_id"]: m["content"] for m in llm.calls[1][0] if m["role"] == "tool"}
    assert results["call-1"] == "x"
    assert "alone" in results["early"]


def test_unparseable_arguments_are_sent_back():
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "echo", {}, invalid_arguments='{"text": ')]),
            submit(),
        ]
    )
    assert investigate("alert", llm=llm, tools=[echo_tool]) == ANSWER
    assert llm.calls[1][0][-1]["content"].startswith("error: arguments are not valid JSON")


def test_last_text_step_and_budget_note_are_one_user_message():
    llm = FakeLLM([Reply(text="thinking out loud"), submit()])
    assert investigate("alert", llm=llm, tools=[], max_steps=1) == ANSWER
    messages = llm.calls[1][0]
    assert [m["role"] for m in messages[-2:]] == ["assistant", "user"]
    assert "budget" in messages[-1]["content"]


def test_invalid_last_chance_submission_says_why():
    calls = [Reply(tool_calls=[ToolCall(f"call-{i}", "echo", {"text": "x"})]) for i in range(2)]
    llm = FakeLLM([*calls, submit("bad", {**ARGS, "status": "maybe"})])
    with pytest.raises(MaxStepsExceeded, match="status"):
        investigate("alert", llm=llm, tools=[echo_tool], max_steps=2)


def test_a_tool_named_submit_answer_is_rejected():
    clash = Tool("submit_answer", "user tool", {"type": "object"}, lambda: "x")
    with pytest.raises(ValueError, match="submit_answer"):
        investigate("alert", llm=FakeLLM([]), tools=[clash])


def test_system_message_is_the_prompt_when_context_is_absent():
    llm = FakeLLM([submit()])
    investigate("alert", llm=llm, tools=[])
    assert llm.calls[0][0][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_context_is_appended_to_the_system_message():
    llm = FakeLLM([submit()])
    investigate("alert", llm=llm, tools=[], context="services: checkout, payments")
    assert llm.calls[0][0][0]["content"] == (
        f"{SYSTEM_PROMPT}\n\nAdditional context from the operator:\nservices: checkout, payments"
    )


def test_empty_context_leaves_the_system_message_unchanged():
    llm = FakeLLM([submit()])
    investigate("alert", llm=llm, tools=[], context="")
    assert llm.calls[0][0][0]["content"] == SYSTEM_PROMPT


def test_main_context_file_reaches_the_system_message(monkeypatch, tmp_path, capsys):
    path = tmp_path / "services.txt"
    path.write_text("services: checkout, payments\n", encoding="utf-8")
    llm = FakeLLM([submit(), submit()])
    monkeypatch.setattr("truesight.agent.llm_from_env", lambda: llm)
    monkeypatch.setattr("truesight.__main__.tools_from_mcp", lambda url: [])

    main(["truesight", "--context-file", str(path), "disk", "full"])
    main(["truesight", "--mcp-url", "http://127.0.0.1:9/mcp", "--context-file", str(path), "x"])

    assert len(llm.calls) == 2
    for messages, _tools in llm.calls:
        assert messages[0]["content"].endswith(
            "Additional context from the operator:\nservices: checkout, payments\n"
        )
    assert capsys.readouterr().out.count('"summary": "disk filled by logs"') == 2


def test_main_prints_the_investigation(monkeypatch, capsys):
    monkeypatch.setattr(
        "truesight.__main__.investigate", lambda alert, tools=None, context=None: ANSWER
    )
    main(["truesight", "disk", "full"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["location"] == {"kind": "resource", "address": "/var/log on db-1"}
    assert printed["evidence"] == [{"tool": "echo", "finding": "95%"}]


def test_main_loads_tools_from_mcp_url(monkeypatch, capsys):
    seen = {}

    def fake_tools(url: str):
        seen["url"] = url
        return [echo_tool]

    def fake_investigate(alert: str, tools=None, context=None):
        seen["alert"] = alert
        seen["tool"] = tools[0].name
        return ANSWER

    monkeypatch.setattr("truesight.__main__.tools_from_mcp", fake_tools)
    monkeypatch.setattr("truesight.__main__.investigate", fake_investigate)
    main(["truesight", "--mcp-url", "http://127.0.0.1:9/mcp", "disk", "full"])
    assert seen == {"url": "http://127.0.0.1:9/mcp", "alert": "disk full", "tool": "echo"}
    assert json.loads(capsys.readouterr().out)["status"] == "established"
