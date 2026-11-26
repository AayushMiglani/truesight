import json

import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.providers.deepseek import DeepSeekProvider
from scripted import ARGS, Scripted, call, submit

from truesight.__main__ import main
from truesight.agent import SYSTEM_PROMPT, MaxStepsExceeded, investigate, model_from_env
from truesight.answer import Answer

ANSWER = Answer.model_validate(ARGS)
ECHO = call("echo", {"text": "95%"}, "echo-1")


def test_model_calls_a_tool_then_submits():
    model = Scripted([ECHO, submit()])
    assert investigate("disk 95%", model=model) == ANSWER
    messages, info = model.calls[0]
    assert "incident" in info.instructions
    assert "submit_answer" in info.instructions
    assert messages[0].parts[-1].content == "disk 95%"
    assert model.tool_names(0) == ["echo", "submit_answer"]
    assert len(model.calls) == 2


def test_echo_result_is_fed_back_then_submitted():
    model = Scripted([call("echo", {"text": "ping"}), submit()])
    assert investigate("check echo", model=model) == ANSWER
    [result] = model.last_parts(1)
    assert (result.tool_call_id, result.content) == ("call-1", "ping")


def test_invalid_submission_is_sent_back_with_the_field():
    model = Scripted([ECHO, submit({**ARGS, "status": "maybe"}, "bad"), submit()])
    assert investigate("alert", model=model) == ANSWER
    [retry] = model.last_parts(2)
    assert retry.tool_call_id == "bad"
    assert "status" in retry.model_response_str()


def test_text_reply_is_sent_back_to_submit():
    model = Scripted([ECHO, ModelResponse(parts=[TextPart("It is the disk.")]), submit()])
    assert investigate("alert", model=model) == ANSWER
    assert len(model.calls) == 3


def test_out_of_steps_offers_only_submit_answer():
    echoes = [call("echo", {"text": "x"}, f"call-{i}") for i in range(3)]
    model = Scripted([*echoes, submit()])
    assert investigate("alert", model=model, max_steps=3) == ANSWER
    assert len(model.calls) == 4
    assert model.tool_names(3) == ["submit_answer"]
    assert "budget" in model.last_parts(3)[-1].content


def test_max_steps_raises_when_the_last_chance_is_not_a_submission():
    echoes = [call("echo", {"text": "x"}, f"call-{i}") for i in range(4)]
    model = Scripted(echoes)
    with pytest.raises(MaxStepsExceeded, match="no final answer after 3 steps"):
        investigate("alert", model=model, max_steps=3)
    assert len(model.calls) == 4


def test_schema_invalid_last_chance_submission_raises():
    model = Scripted([ECHO, submit({**ARGS, "status": "maybe"})])
    with pytest.raises(MaxStepsExceeded):
        investigate("alert", model=model, max_steps=1)


def test_unchecked_last_chance_answer_is_returned_not_established():
    model = Scripted([ECHO, submit({**ARGS, "evidence": [{"tool": "GetLogs", "finding": "x"}]})])
    answer = investigate("alert", model=model, max_steps=1)
    assert answer.status == "not_established"
    assert answer.summary.startswith("disk filled by logs (unchecked: evidence.0.tool:")
    assert answer.evidence[0].tool == "GetLogs"


def test_submit_batched_with_other_calls_is_sent_back():
    batch = ModelResponse(
        parts=[
            ToolCallPart("echo", {"text": "x"}, tool_call_id="call-1"),
            ToolCallPart("submit_answer", ARGS, tool_call_id="early"),
        ]
    )
    model = Scripted([batch, submit()])
    assert investigate("alert", model=model) == ANSWER
    results = {part.tool_call_id: part.model_response_str() for part in model.last_parts(1)}
    assert results["call-1"] == "x"
    assert "alone" in results["early"]


def test_evidence_from_a_tool_never_called_is_sent_back():
    model = Scripted([submit(call_id="unseen"), ECHO, submit()])
    assert investigate("alert", model=model) == ANSWER
    [retry] = model.last_parts(1)
    assert retry.tool_call_id == "unseen"
    assert "evidence.0.tool:" in retry.model_response_str()


def test_instructions_are_the_prompt_when_context_is_absent():
    model = Scripted([ECHO, submit()])
    investigate("alert", model=model)
    assert model.calls[0][1].instructions == SYSTEM_PROMPT


def test_context_is_appended_to_the_instructions():
    model = Scripted([ECHO, submit()])
    investigate("alert", model=model, context="services: checkout, payments")
    assert model.calls[0][1].instructions == (
        f"{SYSTEM_PROMPT}\n\nAdditional context from the operator:\nservices: checkout, payments"
    )


def test_empty_context_leaves_the_instructions_unchanged():
    model = Scripted([ECHO, submit()])
    investigate("alert", model=model, context="")
    assert model.calls[0][1].instructions == SYSTEM_PROMPT


def test_main_context_file_reaches_the_instructions(monkeypatch, tmp_path, capsys):
    path = tmp_path / "services.txt"
    path.write_text("services: checkout, payments\n", encoding="utf-8")
    model = Scripted([ECHO, submit()])
    monkeypatch.setattr("truesight.agent.model_from_env", lambda: model)
    main(["truesight", "--context-file", str(path), "disk", "full"])
    assert model.calls[0][1].instructions.endswith(
        "Additional context from the operator:\nservices: checkout, payments"
    )
    assert json.loads(capsys.readouterr().out)["summary"] == "disk filled by logs"


def test_main_prints_the_investigation(monkeypatch, capsys):
    monkeypatch.setattr("truesight.__main__.investigate", lambda alert, **_: ANSWER)
    main(["truesight", "disk", "full"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["location"] == {"kind": "resource", "address": "/var/log on db-1"}
    assert printed["evidence"] == [{"tool": "echo", "finding": "95%"}]


def test_main_passes_every_mcp_url(monkeypatch, capsys):
    seen = {}

    def fake_investigate(alert, mcp_urls, **_):
        seen.update(alert=alert, urls=mcp_urls)
        return ANSWER

    monkeypatch.setattr("truesight.__main__.investigate", fake_investigate)
    main(["truesight", "--mcp-url", "http://a/mcp", "--mcp-url", "http://b/mcp", "disk", "full"])
    assert seen == {"alert": "disk full", "urls": ["http://a/mcp", "http://b/mcp"]}
    assert json.loads(capsys.readouterr().out)["status"] == "established"


def test_env_model_is_deepseek_and_sends_reasoning_back(monkeypatch):
    monkeypatch.setenv("TRUESIGHT_LLM_API_KEY", "k")
    model = model_from_env()
    assert isinstance(model._provider, DeepSeekProvider)
    assert model.profile.get("openai_chat_thinking_field") == "reasoning_content"
    assert model.profile.get("openai_chat_send_back_thinking_parts") == "field"


def test_system_prompt_allows_not_established():
    assert "not_established" in SYSTEM_PROMPT
    assert "leading candidate" in SYSTEM_PROMPT
