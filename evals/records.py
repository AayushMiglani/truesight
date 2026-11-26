import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

RUN_FILE = "run.json"
RESULTS_FILE = "results.jsonl"
PROMPT_FILE = "prompt.txt"


class Failure(StrEnum):
    AGENT = "agent"
    INFRA = "infra"


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class RunInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    benchmark_ref: str
    model_api: str
    started: datetime
    git_sha: str
    git_dirty: bool
    prompt_sha256: str
    model: str
    max_steps: int
    repeats: int
    timeout_seconds: float
    cases: Sequence[str]
    tag: str = ""


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str
    group: str
    repeat: int
    truth: Mapping[str, Any]
    answer: Mapping[str, Any] | None = None
    metrics: Mapping[str, bool] = Field(default_factory=dict)
    passed: bool = False
    failure: Failure | None = None
    error: str | None = None
    seconds: float
    usage: Usage = Usage()

    @property
    def scored(self) -> bool:
        return self.failure is not Failure.INFRA

    @property
    def key(self) -> tuple[str, int]:
        return (self.case, self.repeat)


def write_info(run_dir: Path, info: RunInfo) -> None:
    (run_dir / RUN_FILE).write_text(info.model_dump_json(indent=2), encoding="utf-8")


def read_info(run_dir: Path) -> RunInfo:
    return RunInfo.model_validate_json((run_dir / RUN_FILE).read_text(encoding="utf-8"))


def append_record(run_dir: Path, record: Record) -> None:
    with (run_dir / RESULTS_FILE).open("a", encoding="utf-8") as out:
        out.write(record.model_dump_json() + "\n")


def read_records(run_dir: Path) -> list[Record]:
    path = run_dir / RESULTS_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return latest([Record.model_validate(json.loads(line)) for line in lines if line.strip()])


def latest(records: Sequence[Record]) -> list[Record]:
    by_key: dict[tuple[str, int], Record] = {}
    for record in records:
        by_key[record.key] = record
    return list(by_key.values())
