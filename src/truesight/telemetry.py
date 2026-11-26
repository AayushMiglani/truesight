import sentry_sdk
from sentry_sdk.integrations.pydantic_ai import PydanticAIIntegration

from truesight.settings import SentrySettings, load


def configure_sentry(settings: SentrySettings | None = None) -> bool:
    settings = settings or load(SentrySettings)
    if settings.dsn is None:
        return False
    content = settings.include_content
    sentry_sdk.init(
        dsn=settings.dsn.get_secret_value(),
        environment=settings.environment,
        traces_sample_rate=settings.traces_sample_rate,
        integrations=[PydanticAIIntegration(handled_tool_call_exceptions=False)],
        data_collection={
            "gen_ai": {"inputs": content, "outputs": content},
            "mcp": {"inputs": content, "outputs": content},
            "stack_frame_variables": content,
        },
    )
    return True
