from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from evals.records import Failure, Record, RunInfo


@dataclass(frozen=True)
class CaseResult:
    case: str
    group: str
    passes: int
    runs: int


@dataclass(frozen=True)
class Summary:
    scored: int
    passed: int
    metrics: dict[str, int]
    cases: list[CaseResult]
    agent_failures: int
    infra_failures: int
    not_established: int
    input_tokens: int
    output_tokens: int
    seconds: float

    @property
    def pass_at_k(self) -> int:
        return sum(c.passes > 0 for c in self.cases)

    @property
    def pass_all_k(self) -> int:
        return sum(c.passes == c.runs for c in self.cases)


def summarize(records: Sequence[Record], metrics: Sequence[str]) -> Summary:
    scored = [r for r in records if r.scored]
    return Summary(
        scored=len(scored),
        passed=sum(r.passed for r in scored),
        metrics={m: sum(bool(r.metrics.get(m)) for r in scored) for m in metrics},
        cases=_cases(scored),
        agent_failures=sum(r.failure is Failure.AGENT for r in records),
        infra_failures=sum(r.failure is Failure.INFRA for r in records),
        not_established=sum(
            r.answer is not None and r.answer.get("status") == "not_established" for r in scored
        ),
        input_tokens=sum(r.usage.input_tokens for r in scored),
        output_tokens=sum(r.usage.output_tokens for r in scored),
        seconds=sum(r.seconds for r in scored),
    )


def _cases(scored: Sequence[Record]) -> list[CaseResult]:
    runs: dict[str, list[Record]] = defaultdict(list)
    for record in scored:
        runs[record.case].append(record)
    return [
        CaseResult(case, rs[0].group, sum(r.passed for r in rs), len(rs))
        for case, rs in sorted(runs.items())
    ]


def format_summary(info: RunInfo, summary: Summary, show_cases: bool = True) -> list[str]:
    n = summary.scored or 1
    k = info.repeats
    lines = [
        f"{info.benchmark} {info.tag or ''} · {info.model} · max_steps {info.max_steps} · "
        f"git {info.git_sha[:7]}{'+dirty' if info.git_dirty else ''} · "
        f"prompt {info.prompt_sha256[:8]}",
        f"passed {summary.passed}/{summary.scored} = {summary.passed / n:.0%}  "
        + "  ".join(f"{m} {v}/{summary.scored}" for m, v in summary.metrics.items()),
        f"cases {len(summary.cases)}: pass@{k} {summary.pass_at_k}  pass^{k} {summary.pass_all_k}",
        f"agent failures {summary.agent_failures} (scored as misses)  "
        f"infra failures {summary.infra_failures} (not scored)  "
        f"not_established {summary.not_established}",
        f"tokens in {summary.input_tokens:,} out {summary.output_tokens:,}  "
        f"mean {summary.seconds / n:.0f}s per run",
    ]
    lines += _groups(summary)
    if show_cases:
        missed = [c for c in summary.cases if c.passes < c.runs]
        lines += [f"  missed {c.case:<36} {c.passes}/{c.runs}" for c in missed]
    return lines


def _groups(summary: Summary) -> list[str]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for case in summary.cases:
        totals[case.group][0] += case.passes
        totals[case.group][1] += case.runs
    return [f"  {group:<28} {p}/{r}" for group, (p, r) in sorted(totals.items())]


def format_comparison(
    names: tuple[str, str], a: Sequence[Record], b: Sequence[Record]
) -> list[str]:
    left, right = _per_case(a), _per_case(b)
    lines = [f"{'case':<36} {names[0]:>12} {names[1]:>12}"]
    for case in sorted(set(left) | set(right)):
        pa, pb = left.get(case), right.get(case)
        if pa != pb or (pa and pa[0] < pa[1]):
            lines.append(f"{case:<36} {_ratio(pa):>12} {_ratio(pb):>12}")
    return lines


def _per_case(records: Sequence[Record]) -> dict[str, tuple[int, int]]:
    return {c.case: (c.passes, c.runs) for c in _cases([r for r in records if r.scored])}


def _ratio(value: tuple[int, int] | None) -> str:
    return "-" if value is None else f"{value[0]}/{value[1]}"
