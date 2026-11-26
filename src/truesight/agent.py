import asyncio
from collections.abc import Sequence
from pathlib import Path

import pydantic_ai
from pydantic_ai import (
    AbstractToolset,
    Agent,
    AgentRunResult,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ModelRetry,
    ModelSettings,
    RunContext,
    ToolCallPart,
    ToolOutput,
    ToolReturnPart,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from truesight.answer import Answer, answer_error
from truesight.prompts import (
    OUT_OF_STEPS,
    SUBMIT_ALONE,
    SUBMIT_ANSWER,
    SUBMIT_DESCRIPTION,
    SYSTEM_PROMPT,
    instructions,
)
from truesight.settings import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_SECONDS, LLMSettings, load
from truesight.tools import echo_toolset

pydantic_ai.BANNER_ENABLED = False

DEFAULT_MAX_STEPS = 8
DEFAULT_MODEL_SETTINGS = ModelSettings(
    timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=DEFAULT_MAX_RETRIES
)

Toolsets = list[AbstractToolset[None]]


class MaxStepsExceeded(Exception):
    pass


def investigate(
    alert: str,
    model: Model | None = None,
    mcp_urls: Sequence[str] = (),
    max_steps: int = DEFAULT_MAX_STEPS,
    context: str | None = None,
    trace: Path | None = None,
    prompt: str | None = None,
) -> Answer:
    return asyncio.run(
        investigate_async(
            alert,
            model=model,
            mcp_urls=mcp_urls,
            max_steps=max_steps,
            context=context,
            trace=trace,
            prompt=prompt,
        )
    )


async def investigate_async(
    alert: str,
    *,
    model: Model | None = None,
    mcp_urls: Sequence[str] = (),
    max_steps: int = DEFAULT_MAX_STEPS,
    context: str | None = None,
    trace: Path | None = None,
    prompt: str | None = None,
) -> Answer:
    model = model or model_from_env()
    settings = _model_settings(model)
    text = instructions(prompt or SYSTEM_PROMPT, context)
    agent = _agent(model, settings, _toolsets(mcp_urls), text, max_steps, final=False)
    async with agent:
        with capture_run_messages() as messages:
            try:
                result = await agent.run(alert, usage_limits=UsageLimits(request_limit=max_steps))
            except UsageLimitExceeded:
                result = await _final_turn(model, settings, messages, text, max_steps, trace)
            except Exception:
                _write_trace(trace, messages)
                raise
    _write_trace(trace, result.all_messages())
    return result.output


def model_from_env(settings: LLMSettings | None = None) -> Model:
    settings = settings or load(LLMSettings)
    provider = DeepSeekProvider(
        api_key=settings.api_key.get_secret_value(),
        base_url=str(settings.base_url).rstrip("/"),
    )
    return OpenAIChatModel(
        settings.model,
        provider=provider,
        settings=ModelSettings(timeout=settings.timeout_seconds, max_retries=settings.max_retries),
    )


def _model_settings(model: Model) -> ModelSettings:
    return model.settings or DEFAULT_MODEL_SETTINGS


async def _final_turn(
    model: Model,
    settings: ModelSettings,
    messages: list[ModelMessage],
    text: str,
    max_steps: int,
    trace: Path | None,
) -> AgentRunResult[Answer]:
    agent = _agent(model, settings, [], text, max_steps, final=True)
    with capture_run_messages() as captured:
        try:
            return await agent.run(
                OUT_OF_STEPS,
                message_history=list(messages),
                usage_limits=UsageLimits(request_limit=1),
            )
        except (UsageLimitExceeded, UnexpectedModelBehavior) as exc:
            _write_trace(trace, captured)
            raise MaxStepsExceeded(f"no final answer after {max_steps} steps ({exc})") from exc
        except Exception:
            _write_trace(trace, captured)
            raise


def _write_trace(trace: Path | None, messages: Sequence[ModelMessage]) -> None:
    if trace is not None:
        trace.write_bytes(ModelMessagesTypeAdapter.dump_json(list(messages)))


def _toolsets(mcp_urls: Sequence[str]) -> Toolsets:
    if not mcp_urls:
        return [echo_toolset]
    servers = [MCPToolset(url, tool_error_behavior="failed") for url in mcp_urls]
    if len(servers) == 1:
        return list(servers)
    return [server.prefixed(f"mcp{i}") for i, server in enumerate(servers, start=1)]


def _agent(
    model: Model,
    settings: ModelSettings,
    toolsets: Toolsets,
    text: str,
    max_steps: int,
    final: bool,
) -> Agent[None, Answer]:
    agent = Agent(
        model,
        deps_type=type(None),
        name="truesight",
        output_type=ToolOutput(Answer, name=SUBMIT_ANSWER, description=SUBMIT_DESCRIPTION),
        instructions=text,
        toolsets=toolsets,
        retries=max_steps,
        model_settings=settings,
    )

    @agent.output_validator
    def check(ctx: RunContext[None], answer: Answer) -> Answer:
        if not final and _has_other_calls(ctx.messages):
            raise ModelRetry(SUBMIT_ALONE)
        error = answer_error(answer, _called_tools(ctx.messages))
        if error is None:
            return answer
        if not final:
            raise ModelRetry(error)
        summary = f"{answer.summary} (unchecked: {error})"
        return answer.model_copy(update={"status": "not_established", "summary": summary})

    return agent


def _has_other_calls(messages: Sequence[ModelMessage]) -> bool:
    last = messages[-1]
    return isinstance(last, ModelResponse) and any(
        isinstance(part, ToolCallPart) and part.tool_name != SUBMIT_ANSWER for part in last.parts
    )


def _called_tools(messages: Sequence[ModelMessage]) -> set[str]:
    return {
        part.tool_name
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
        and part.outcome in ("success", "failed")
        and part.tool_name != SUBMIT_ANSWER
    }
