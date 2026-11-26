from pydantic import Field, HttpUrl, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_RETRIES = 2


class ConfigError(Exception):
    pass


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRUESIGHT_LLM_", env_ignore_empty=True, frozen=True
    )

    api_key: SecretStr = Field(min_length=1)
    base_url: HttpUrl = HttpUrl("https://api.deepseek.com")
    model: str = Field(default="deepseek-flash", min_length=1)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)


class SentrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRUESIGHT_SENTRY_", env_ignore_empty=True, frozen=True
    )

    dsn: SecretStr | None = None
    environment: str = "development"
    traces_sample_rate: float = Field(default=1.0, ge=0, le=1)
    include_content: bool = False


def load[T: BaseSettings](cls: type[T]) -> T:
    try:
        return cls()
    except ValidationError as exc:
        prefix = cls.model_config.get("env_prefix", "")
        problems = "; ".join(
            f"{prefix}{str(error['loc'][0]).upper()}: {error['msg']}" for error in exc.errors()
        )
        raise ConfigError(f"invalid configuration: {problems}") from exc
