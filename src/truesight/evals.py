"""Load an eval case and grade a written incident report against it."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Case:
    name: str
    incident: str
    logs: str
    deploys: str
    root_cause: str
    must_mention: list[str]
    decoy: list[str]


@dataclass
class Grade:
    passed: bool
    reason: str


def load_case(path: Path) -> Case:
    """Read incident.md, logs.jsonl, deploys.json, and answer.json from path."""
    answer = json.loads((path / "answer.json").read_text(encoding="utf-8"))
    return Case(
        name=path.name,
        incident=(path / "incident.md").read_text(encoding="utf-8"),
        logs=(path / "logs.jsonl").read_text(encoding="utf-8"),
        deploys=(path / "deploys.json").read_text(encoding="utf-8"),
        root_cause=answer["root_cause"],
        must_mention=answer["must_mention"],
        decoy=answer["decoy"],
    )


def grade(report_text: str, case: Case) -> Grade:
    """Pass if every must_mention keyword is present and no decoy keyword is."""
    text = report_text.lower()

    missing = [word for word in case.must_mention if word.lower() not in text]
    if missing:
        return Grade(passed=False, reason="missing keyword: " + ", ".join(missing))

    # Any decoy keyword fails the report, even in a sentence that rules it out.
    named = [word for word in case.decoy if word.lower() in text]
    if named:
        return Grade(passed=False, reason="names the decoy: " + ", ".join(named))

    return Grade(
        passed=True,
        reason="mentions the required evidence and does not name the decoy",
    )


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m truesight.evals CASE report.txt", file=sys.stderr)
        return 2

    case_name = sys.argv[1]
    report_name = sys.argv[2]
    case_dir = Path("evals") / "cases" / case_name
    report_path = Path(report_name)
    if not case_dir.is_dir():
        print("FAIL")
        print(f"no such case: {case_name}")
        return 1
    if not report_path.is_file():
        print("FAIL")
        print(f"no such report: {report_path}")
        return 1

    result = grade(report_path.read_text(encoding="utf-8"), load_case(case_dir))
    print("PASS" if result.passed else "FAIL")
    print(result.reason)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
