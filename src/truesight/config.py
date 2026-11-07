"""truesight.toml loading. See truesight.example.toml."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    raw: dict

    @property
    def sentry(self) -> dict:
        return self.raw["sentry"]

    @property
    def cloudwatch(self) -> dict:
        return self.raw.get("cloudwatch", {})

    @property
    def deploys(self) -> dict:
        return self.raw.get("deploys", {})

    @property
    def metrics(self) -> list[dict]:
        return self.raw.get("metrics", [])

    @property
    def llm(self) -> dict:
        return self.raw.get("llm", {})

    @property
    def services(self) -> dict[str, dict]:
        return self.raw.get("services", {})

    def service_for_sentry_project(self, project: str) -> str:
        """Service map lookup. Unmapped projects are their own service name."""
        for name, ids in self.services.items():
            if ids.get("sentry", name) == project:
                return name
        return project

    def secret(self, env_name: str) -> str:
        value = os.environ.get(env_name)
        if not value:
            raise SystemExit(f"{env_name} is not set (named in truesight.toml)")
        return value


def load(path: str | Path) -> Config:
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit(f"config not found: {p} (copy truesight.example.toml)")
    with p.open("rb") as f:
        raw = tomllib.load(f)
    if "sentry" not in raw:
        raise SystemExit(f"{p}: [sentry] section is required")
    return Config(raw)
