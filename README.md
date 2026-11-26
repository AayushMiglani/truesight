# truesight

truesight will investigate an incident: read logs, deploys, and metrics,
name the likely root cause, and explain it. This repository holds the agent.
Eval data stays outside the repository; see Evals.

## Setup

Python 3.12 and uv. From the repository root, run `uv sync`.

The agent runs on [Pydantic AI](https://pydantic.dev/docs/ai/). The model is DeepSeek
through its OpenAI-compatible chat API. Copy `.env.example` to `.env` and set:

- `TRUESIGHT_LLM_API_KEY` — required
- `TRUESIGHT_LLM_BASE_URL` — optional, default `https://api.deepseek.com`
- `TRUESIGHT_LLM_MODEL` — optional, default `deepseek-flash`
- `TRUESIGHT_LLM_TIMEOUT_SECONDS`, `TRUESIGHT_LLM_MAX_RETRIES` — optional, default 180 and 2

Settings are checked at startup; a missing or invalid value exits with code 2 and names the variable.

To send traces to Sentry (agent run, each model request with token usage, each tool call), set
`TRUESIGHT_SENTRY_DSN`. Optional: `TRUESIGHT_SENTRY_ENVIRONMENT` (default `development`),
`TRUESIGHT_SENTRY_TRACES_SAMPLE_RATE` (default 1.0). Prompts, tool output and stack-frame
variables are left out unless `TRUESIGHT_SENTRY_INCLUDE_CONTENT=true`, because incident data can
hold customer data.

## Run

```bash
uv run --env-file .env python -m truesight "disk full on db-1"
```

`--env-file` makes uv load the variables from `.env` (alternatively, export them in the shell). With no arguments the command prints usage and exits 0.

To use tools from an MCP server over Streamable HTTP, pass its URL. Repeat `--mcp-url` for
more servers; with more than one, each server's tools are prefixed `mcp1_`, `mcp2_`, … in the
order given. Without `--mcp-url`, truesight keeps its built-in echo tool.

```bash
uv run --env-file .env python -m truesight --mcp-url http://127.0.0.1:8000/mcp "disk full on db-1"
```

`--context-file` reads a UTF-8 text file and appends it to the system prompt, with or without `--mcp-url`. Use it for a list of service names or a short runbook.

```bash
uv run --env-file .env python -m truesight --context-file services.txt "disk full on db-1"
```

`--trace PATH` writes the run's full message history (tool calls, results, reasoning) as JSON.

The agent has 8 model requests. It finishes by calling its built-in `submit_answer` tool; the
answer is checked against its schema, an `established` answer must rule something out, and
every `evidence` and `ruled_out` entry must name a tool that ran. A failing answer is sent back
to the model to fix. When the budget runs out, the model gets one last request offering only
`submit_answer`; an answer that fails the checks there is returned as `not_established` with
the reason in `summary`. The command prints the answer as indented JSON and exits 0 when
`established`, 3 when `not_established`, 1 when the run fails, 2 on bad input or settings.
The alert is limited to 4,000 characters and `--context-file` to 100,000. Answer fields:

- `status`: `established` or `not_established`
- `summary`: one sentence, what is wrong and where
- `component`, `fault_type`: the thing at fault and a short label for the kind of fault
- `location`: `kind` (code, config, change, resource, dependency, other) and `address`
  (file and line, config key, commit, or resource name)
- `mechanism`: how the fault produces the symptom
- `evidence`: the tool calls and what their output showed
- `ruled_out`: other explanations checked and why each was dropped

## Evals

`evals/` runs truesight on benchmark cases and scores the answers. Each benchmark is an
adapter (`evals/benchmarks/`) that lists cases, starts a case's environment (its MCP servers)
and scores an answer; the runner is shared. Benchmark data stays outside the repository.

Cloud-OpsBench: set `CLOUDOPSBENCH_DIR` to a checkout with its `.venv` set up.

```bash
uv run --env-file .env python -m evals run cloudopsbench --cases-file dev.txt --repeats 3
uv run --env-file .env python -m evals resume runs/evals/<run>
uv run python -m evals report runs/evals/<run>
uv run python -m evals compare runs/evals/<run-a> runs/evals/<run-b>
```

`run` options: `--cases-file` (one case id or path per line) or `--sample N --seed S`
(stratified by group), `--repeats K`, `--jobs`, `--max-steps` (default 15), `--timeout`
(seconds per run, default 900), `--prompt-file`, `--model-api chat|responses`, `--tag`.
A local adapter can be passed as a path to a `.py` file that defines `create_benchmark()`.

Each run directory (under `TRUESIGHT_EVAL_RUNS_DIR`, default `runs/evals`) holds `run.json`
(git SHA, prompt hash, model, settings, cases), `prompt.txt`, `results.jsonl` (one record per
case and repeat) and `logs/` (trace and MCP server log per run). A run that fails because of
the model provider, the environment or the timeout is an infra failure: it is not scored, and
`resume` runs it again. A run that ends without a valid answer is an agent failure and scores
as a miss. `report` shows pass@k (cases passed at least once) and pass^k (cases passed every
time), per-group results, failures and tokens.

## Tests and lint

```bash
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest -q
```
