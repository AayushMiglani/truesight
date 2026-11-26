import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from evals.benchmark import Benchmark, Case
from evals.records import PROMPT_FILE, Record, RunInfo, read_info, read_records, write_info
from evals.report import format_comparison, format_summary, summarize
from evals.runner import RunOptions, run, select
from evals.setup import ModelApi, git_state, load_benchmark, model_factory, sha256
from truesight.prompts import SYSTEM_PROMPT
from truesight.settings import ConfigError
from truesight.telemetry import configure_sentry

RUNS_DIR = Path(os.environ.get("TRUESIGHT_EVAL_RUNS_DIR", "runs/evals"))
DEFAULT_MAX_STEPS = 15
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_JOBS = 8


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.command(args)
    except (ConfigError, ValueError, FileNotFoundError) as exc:
        print(f"evals: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals")
    commands = parser.add_subparsers(required=True)

    start = commands.add_parser("run", help="start a new eval run")
    start.add_argument("benchmark", help="built-in name (cloudopsbench) or path to a .py adapter")
    picked = start.add_mutually_exclusive_group()
    picked.add_argument("--cases-file", type=Path, help="one case id or path per line")
    picked.add_argument("--sample", type=int, help="stratified sample of N cases")
    start.add_argument("--seed", type=int, default=0)
    start.add_argument("--repeats", type=int, default=1, help="runs per case (k)")
    start.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    start.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    start.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    start.add_argument("--prompt-file", type=Path)
    start.add_argument("--model-api", type=ModelApi, choices=list(ModelApi), default="chat")
    start.add_argument("--tag", default="")
    start.set_defaults(command=_start)

    resume = commands.add_parser("resume", help="finish a run: redo missing and infra-failed runs")
    resume.add_argument("run_dir", type=Path)
    resume.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    resume.set_defaults(command=_resume)

    report = commands.add_parser("report", help="summarize a run")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(command=_report)

    compare = commands.add_parser("compare", help="compare two runs case by case")
    compare.add_argument("run_a", type=Path)
    compare.add_argument("run_b", type=Path)
    compare.set_defaults(command=_compare)
    return parser


def _start(args: argparse.Namespace) -> int:
    benchmark = load_benchmark(args.benchmark)
    wanted = _read_lines(args.cases_file) if args.cases_file else None
    cases = select(benchmark.cases(), wanted, args.sample, args.seed)
    prompt = args.prompt_file.read_text(encoding="utf-8").strip() if args.prompt_file else None
    effective_prompt = prompt or SYSTEM_PROMPT
    factory = model_factory(args.model_api)
    git_sha, git_dirty = git_state()
    info = RunInfo(
        benchmark=benchmark.name,
        benchmark_ref=args.benchmark,
        model_api=args.model_api,
        started=datetime.now().astimezone(),
        git_sha=git_sha,
        git_dirty=git_dirty,
        prompt_sha256=sha256(effective_prompt),
        model=factory().model_name,
        max_steps=args.max_steps,
        repeats=args.repeats,
        timeout_seconds=args.timeout,
        cases=[c.id for c in cases],
        tag=args.tag,
    )
    stamp = info.started.strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / "-".join(filter(None, [stamp, benchmark.name, args.tag]))
    run_dir.mkdir(parents=True)
    write_info(run_dir, info)
    (run_dir / PROMPT_FILE).write_text(effective_prompt, encoding="utf-8")
    options = RunOptions(
        factory, args.repeats, args.jobs, args.max_steps, args.timeout, effective_prompt
    )
    return _execute(benchmark, cases, options, run_dir, info)


def _resume(args: argparse.Namespace) -> int:
    info = read_info(args.run_dir)
    benchmark = load_benchmark(info.benchmark_ref)
    cases = select(benchmark.cases(), info.cases, None, 0)
    prompt = (args.run_dir / PROMPT_FILE).read_text(encoding="utf-8")
    if sha256(prompt) != info.prompt_sha256:
        raise ValueError(f"{PROMPT_FILE} no longer matches the run's prompt hash")
    options = RunOptions(
        model_factory(ModelApi(info.model_api)),
        info.repeats,
        args.jobs,
        info.max_steps,
        info.timeout_seconds,
        prompt,
    )
    return _execute(benchmark, cases, options, args.run_dir, info)


def _execute(
    benchmark: Benchmark, cases: list[Case], options: RunOptions, run_dir: Path, info: RunInfo
) -> int:
    configure_sentry()
    print(f"run dir: {run_dir}", flush=True)
    asyncio.run(run(benchmark, cases, options, run_dir, _print_record))
    for line in format_summary(info, summarize(read_records(run_dir), benchmark.metrics)):
        print(line)
    return 0


def _report(args: argparse.Namespace) -> int:
    info = read_info(args.run_dir)
    records = read_records(args.run_dir)
    metrics = sorted({m for r in records for m in r.metrics})
    for line in format_summary(info, summarize(records, metrics)):
        print(line)
    return 0


def _compare(args: argparse.Namespace) -> int:
    names = (args.run_a.name[-12:], args.run_b.name[-12:])
    a, b = read_records(args.run_a), read_records(args.run_b)
    metrics = sorted({m for r in [*a, *b] for m in r.metrics})
    for run_dir, records in ((args.run_a, a), (args.run_b, b)):
        summary = summarize(records, metrics)
        print(f"{run_dir.name}: passed {summary.passed}/{summary.scored}")
    for line in format_comparison(names, a, b):
        print(line)
    return 0


def _print_record(record: Record) -> None:
    got = record.answer or {}
    truth = " / ".join(str(v) for v in record.truth.values())
    outcome = "PASS" if record.passed else (record.failure or "miss")
    print(
        f"{record.case:<32} r{record.repeat} {outcome:<5} "
        f"got {got.get('component', '-')} / {got.get('fault_type', '-')}  want {truth}"
        + (f"  {record.error}" if record.error else ""),
        flush=True,
    )


def _read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
