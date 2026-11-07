"""`truesight eval golden.toml`: score Reports against incidents whose root cause is known.

Each incident is gathered once (or loaded from a saved run with --replay), then synthesised
`runs` times, because the same ledger can give different Reports. A model call judges each
Report against the known cause, since keyword matching cannot tell "the deploy is not the
cause" from blaming the deploy.

golden.toml:
    [[incident]]
    name = "G1"
    ref = "sentry:API-1AZ"
    at = "2026-10-23T11:30Z"
    cause = "PR #123 in image abc123 stopped setting userId, so the URL had an empty segment"
    decoy = "the 10:02 payments deploy"   # optional: a plausible wrong answer
"""

import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from truesight import render
from truesight.cli import _parse_at
from truesight.config import Config
from truesight.gather import gather
from truesight.model import Report
from truesight.synthesis import Llm, parse_json, synthesise

PLACES = ("root_cause", "top_hypothesis", "other_hypothesis", "missed")

JUDGE = """You grade an incident Report against the known root cause. Reply with JSON only:
{"cause_place": "root_cause" | "top_hypothesis" | "other_hypothesis" | "missed",
 "decoy_blamed": true | false, "note": str}

cause_place: where the Report states the known cause (the same mechanism, not just the same
service). "root_cause" only if its root cause states it; a root cause that says "undetermined"
but names it as a possibility is "top_hypothesis" or "other_hypothesis" by where it appears.
decoy_blamed: true only if the root cause or a Finding presents the decoy as a cause. Listing
it as a Hypothesis or ruling it out is not blaming it. If no decoy is given, false."""


@dataclass(frozen=True)
class Score:
    incident: str
    run: int
    cause_place: str
    decoy_blamed: bool
    note: str


def load_golden(path: Path) -> list[dict]:
    incidents = tomllib.loads(path.read_text()).get("incident", [])
    for i in incidents:
        missing = {"name", "ref", "cause"} - set(i)
        if missing:
            raise ValueError(f"{path}: incident {i.get('name', '?')} lacks {sorted(missing)}")
    return incidents


def judge(llm: Llm, incident: dict, report: Report) -> tuple[str, bool, str]:
    hyps = "\n".join(f"{h.id}: {h.claim}" for h in report.hypotheses) or "(none)"
    finds = "\n".join(f"{f.id}: {f.claim}" for f in report.findings) or "(none)"
    user = (f"KNOWN CAUSE: {incident['cause']}\nDECOY: {incident.get('decoy', '(none)')}\n\n"
            f"ROOT CAUSE: {report.root_cause}\n\nFINDINGS:\n{finds}\n\nHYPOTHESES (in order):\n{hyps}")
    verdict = parse_json(llm(JUDGE, user))
    place = verdict.get("cause_place")
    if place not in PLACES:
        raise ValueError(f"judge returned cause_place={place!r}")
    return place, bool(verdict.get("decoy_blamed")), str(verdict.get("note", ""))


def summarise(scores: list[Score]) -> list[str]:
    """One line per incident: how often the cause landed where, and decoy blames."""
    lines = [f"{'incident':<10} {'root cause':>10} {'top hyp':>8} {'other':>6} {'missed':>7} {'decoy':>6}"]
    for name in dict.fromkeys(s.incident for s in scores):
        mine = [s for s in scores if s.incident == name]
        n = len(mine)
        count = {p: sum(s.cause_place == p for s in mine) for p in PLACES}
        decoys = sum(s.decoy_blamed for s in mine)
        lines.append(f"{name:<10} {count['root_cause']:>8}/{n} {count['top_hypothesis']:>6}/{n}"
                     f" {count['other_hypothesis']:>4}/{n} {count['missed']:>5}/{n} {decoys:>4}/{n}")
    return lines


def run_incident(cfg: Config, llm: Llm, incident: dict, runs: int, replay: Path | None, out: Path) -> list[Score]:
    name = incident["name"]
    try:
        if replay:
            trigger, evidence, gaps = render.ledger_from_json((replay / f"{name}.json").read_text())
        else:
            at = _parse_at(incident["at"]) if incident.get("at") else None
            trigger, evidence, gaps = gather(cfg, incident["ref"], at)
    except Exception as e:  # one incident failing to load must not end the eval
        return [Score(name, 0, "missed", False, f"could not gather: {e}")]
    scores = []
    for run in range(1, runs + 1):
        try:
            report = synthesise(llm, trigger, evidence, gaps)
            (out / (f"{name}.json" if run == 1 else f"{name}.run{run}.json")).write_text(render.as_json(report))
            scores.append(Score(name, run, *judge(llm, incident, report)))
        except ValueError as e:  # bad model JSON: count as a miss, keep going
            scores.append(Score(name, run, "missed", False, f"run failed: {e}"))
    return scores


def evaluate(cfg: Config, llm: Llm, golden: Path, runs: int, replay: Path | None, out: Path) -> list[Score]:
    incidents = load_golden(golden)
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda i: run_incident(cfg, llm, i, runs, replay, out), incidents)
        scores = [s for batch in results for s in batch]
    (out / "scores.json").write_text(render.as_json_value([s.__dict__ for s in scores]))
    return scores
