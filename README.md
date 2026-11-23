# truesight

truesight will investigate an incident: read logs, deploys, and metrics,
name the likely root cause, and explain it. This repository holds the agent.
Eval data stays local; set `TRUESIGHT_BENCH_DIR` to a Cloud-OpsBench checkout.

## Setup

Python 3.12 and uv. From the repository root, run `uv sync`.

The model is DeepSeek through the OpenAI-compatible API. Copy `.env.example`
to `.env` and set:

- `TRUESIGHT_LLM_API_KEY` — required
- `TRUESIGHT_LLM_BASE_URL` — optional, default `https://api.deepseek.com`
- `TRUESIGHT_LLM_MODEL` — optional, default `deepseek-flash`

## Run

```bash
uv run --env-file .env python -m truesight "disk full on db-1"
```

`--env-file` makes uv load the variables from `.env` (alternatively, export them in the shell). With no arguments the command prints usage and exits 0.

To use tools from an MCP server over Streamable HTTP, pass its URL. Without `--mcp-url`, truesight keeps its built-in echo tool.

```bash
uv run --env-file .env python -m truesight --mcp-url http://127.0.0.1:8000/mcp "disk full on db-1"
```

`--context-file` reads a UTF-8 text file and appends it to the system prompt, with or without `--mcp-url`. Use it for a list of service names or a short runbook.

```bash
uv run --env-file .env python -m truesight --context-file services.txt "disk full on db-1"
```

The agent finishes by calling its built-in `submit_answer` tool; the arguments are checked
against a JSON schema and an invalid answer is sent back to the model to fix. The command
prints the answer as indented JSON:

- `status`: `established` or `not_established`
- `summary`: one sentence, what is wrong and where
- `component`, `fault_type`: the thing at fault and a short label for the kind of fault
- `location`: `kind` (code, config, change, resource, dependency, other) and `address`
  (file and line, config key, commit, or resource name)
- `mechanism`: how the fault produces the symptom
- `evidence`: the tool calls and what their output showed
- `ruled_out`: other explanations checked and why each was dropped

## Tests and lint

```bash
uv run ruff check
uv run ruff format --check
uv run pytest -q
```
