from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from truesight.answer import Answer


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    group: str
    alert: str
    context: str | None = None
    truth: Mapping[str, Any]
    source: str


class Score(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: Mapping[str, bool]
    passed: bool


class Benchmark(Protocol):
    name: str
    metrics: Sequence[str]

    def cases(self) -> list[Case]: ...

    def environment(self, case: Case, log_dir: Path) -> AbstractAsyncContextManager[list[str]]: ...

    def score(self, case: Case, answer: Answer) -> Score: ...
