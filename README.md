# truesight

truesight will investigate an incident: read logs, deploys, and metrics,
name the likely root cause, and explain it. This repository holds the agent.
Eval data stays local; set `TRUESIGHT_BENCH_DIR` to a Cloud-OpsBench checkout.

## Setup

Python 3.12 and uv. From the repository root, run `uv sync`.

## Tests and lint

```bash
uv run ruff check
uv run ruff format --check
uv run pytest -q
```
