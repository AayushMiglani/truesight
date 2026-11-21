# truesight

truesight will investigate an incident: read logs, deploys, and metrics,
name the likely root cause, and explain the evidence. This repository is
only the test bed, with one made-up incident and a grader. The agent loop
comes in a later change.

## Tests

Python 3.12 and uv. From the repository root:

```bash
uv sync --locked
uv run pytest -q
uv run python -m truesight.evals L01 report.txt
```

The last command prints PASS or FAIL and the reason.

## Eval case format

`evals/cases/<id>/` has four files:

- `incident.md` — the alert a person on call would see
- `logs.jsonl` — log lines from the services around that time
- `deploys.json` — recent deploys, including one decoy
- `answer.json` — `root_cause` (one sentence), `must_mention` (lowercase keywords), `decoy` (keywords for the decoy deploy)

A report passes when it contains every `must_mention` keyword (case-insensitive) and does not name the decoy.
