from types import SimpleNamespace

from truesight.llm import OpenAICompatibleLLM


def _client_returning(message):
    create = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=message)])  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _message(content, reasoning, tool_calls=None):
    return SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_extra={"reasoning_content": reasoning} if reasoning is not None else {},
    )


def _llm(message):
    llm = OpenAICompatibleLLM(base_url="http://127.0.0.1:9", api_key="k", model="m")
    llm.client = _client_returning(message)
    return llm


def test_reasoning_is_kept_on_a_tool_call_reply():
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="echo", arguments='{"a": 1}'))
    reply = _llm(_message("", "thinking about it", [call])).complete([], [])
    assert reply.reasoning == "thinking about it"
    assert reply.tool_calls[0].arguments == {"a": 1}


def test_reasoning_is_kept_on_a_text_reply():
    assert _llm(_message("done", "why")).complete([], []).reasoning == "why"


def test_reasoning_survives_the_real_sdk_message_type():
    from openai.types.chat import ChatCompletionMessage

    message = ChatCompletionMessage.model_validate(
        {"role": "assistant", "content": "done", "reasoning_content": "because"}
    )
    assert _llm(message).complete([], []).reasoning == "because"


def test_unparseable_arguments_are_marked_not_raised():
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="echo", arguments='{"a": '))
    reply = _llm(_message("", None, [call])).complete([], [])
    assert reply.tool_calls[0].arguments == {}
    assert reply.tool_calls[0].invalid_arguments == '{"a": '


def test_missing_reasoning_is_none():
    assert _llm(_message("done", None)).complete([], []).reasoning is None
