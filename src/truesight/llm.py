"""Bring-your-own model through LiteLLM: Anthropic API, Bedrock, DeepSeek, OpenAI-compatible,
or local. The provider is a config choice; check what your data policy allows."""

from truesight.config import Config


def from_config(cfg: Config):
    settings = cfg.llm
    model = settings.get("model")
    if not model:
        raise SystemExit("[llm] model is not set in truesight.toml (or pass --no-llm)")

    def complete(system: str, user: str) -> str:
        import litellm  # deferred: heavy import

        resp = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=settings.get("max_tokens", 4000),
            temperature=0,
        )
        return resp.choices[0].message.content

    return complete
