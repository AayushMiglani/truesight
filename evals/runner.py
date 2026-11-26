import asyncio
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import (
    ModelMessagesTypeAdapter,
    ModelResponse,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import Model

from evals.benchmark import Benchmark, Case
from evals.records import Failure, Record, Usage, append_record, read_records
from truesight.agent import MaxStepsExceeded, investigate_async

AGENT_FAILURES = (MaxStepsExceeded, UnexpectedModelBehavior, UsageLimitExceeded)


@dataclass(frozen=True)
class RunOptions:
    model_factory: Callable[[], Model]
    repeats: int
    jobs: int
    max_steps: int
    timeout_seconds: float
    prompt: str | None = None


def select(
    cases: Sequence[Case], wanted: Sequence[str] | None, sample: int | None, seed: int
) -> list[Case]:
    if wanted is not None:
        return _by_name(cases, wanted)
    if sample is None:
        return list(cases)
    return _stratified(cases, sample, seed)


def _by_name(cases: Sequence[Case], wanted: Sequence[str]) -> list[Case]:
    picked = []
    for name in wanted:
        found = [c for c in cases if name.rstrip("/") == c.id or name.endswith("/" + c.id)]
        if len(found) != 1:
            raise ValueError(f"{name!r} matches {len(found)} cases")
        picked.append(found[0])
    return picked


def _stratified(cases: Sequence[Case], sample: int, seed: int) -> list[Case]:
    groups: dict[str, list[Case]] = {}
    for case in sorted(cases, key=lambda c: c.id):
        groups.setdefault(case.group, []).append(case)
    rng = random.Random(seed)  # noqa: S311
    shuffled = {name: _shuffled(rng, members) for name, members in groups.items()}
    picked: list[Case] = []
    for round_ in range(max(len(m) for m in shuffled.values())):
        for name in sorted(shuffled):
            if round_ < len(shuffled[name]) and len(picked) < sample:
                picked.append(shuffled[name][round_])
    return picked


def _shuffled(rng: random.Random, members: list[Case]) -> list[Case]:
    copy = list(members)
    rng.shuffle(copy)
    return copy


async def run(
    benchmark: Benchmark,
    cases: Sequence[Case],
    options: RunOptions,
    run_dir: Path,
    on_record: Callable[[Record], None],
) -> list[Record]:
    done = {r.key for r in read_records(run_dir) if r.scored}
    todo = [
        (case, repeat)
        for repeat in range(1, options.repeats + 1)
        for case in cases
        if (case.id, repeat) not in done
    ]
    gate = asyncio.Semaphore(options.jobs)

    async def one(case: Case, repeat: int) -> Record:
        async with gate:
            record = await run_case(benchmark, case, repeat, options, run_dir)
        append_record(run_dir, record)
        on_record(record)
        return record

    return list(await asyncio.gather(*(one(case, repeat) for case, repeat in todo)))


async def run_case(
    benchmark: Benchmark, case: Case, repeat: int, options: RunOptions, run_dir: Path
) -> Record:
    name = f"{case.id.replace('/', '-')}--r{repeat}"
    log_dir = run_dir / "logs" / name
    log_dir.mkdir(parents=True, exist_ok=True)
    trace = log_dir / "trace.json"
    trace.unlink(missing_ok=True)
    base = {"case": case.id, "group": case.group, "repeat": repeat, "truth": case.truth}
    started = time.monotonic()
    try:
        async with asyncio.timeout(options.timeout_seconds):
            async with benchmark.environment(case, log_dir) as mcp_urls:
                answer = await investigate_async(
                    case.alert,
                    model=options.model_factory(),
                    mcp_urls=mcp_urls,
                    max_steps=options.max_steps,
                    context=case.context,
                    trace=trace,
                    prompt=options.prompt,
                )
    except AGENT_FAILURES as exc:
        return Record(**base, **_failed(Failure.AGENT, exc, started, trace))
    except Exception as exc:
        return Record(**base, **_failed(Failure.INFRA, exc, started, trace))
    score = benchmark.score(case, answer)
    return Record(
        **base,
        answer=answer.model_dump(),
        metrics=score.metrics,
        passed=score.passed,
        seconds=_since(started),
        usage=usage_from_trace(trace),
    )


def _failed(failure: Failure, exc: BaseException, started: float, trace: Path) -> dict:
    return {
        "failure": failure,
        "error": f"{type(exc).__name__}: {exc}",
        "seconds": _since(started),
        "usage": usage_from_trace(trace),
    }


def _since(started: float) -> float:
    return round(time.monotonic() - started, 1)


def usage_from_trace(trace: Path) -> Usage:
    if not trace.exists():
        return Usage()
    messages = ModelMessagesTypeAdapter.validate_json(trace.read_bytes())
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    return Usage(
        requests=len(responses),
        input_tokens=sum(r.usage.input_tokens for r in responses),
        output_tokens=sum(r.usage.output_tokens for r in responses),
    )
