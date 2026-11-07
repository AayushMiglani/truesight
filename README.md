<img src="assets/icon.svg" width="64" height="64" alt="">

# truesight

Investigates a production error on your own infrastructure: follows the failing request across services, lines it up with deploys, and reports what happened with Evidence behind every claim. A claim the Evidence does not back is shown as a Hypothesis, never as a Finding.

v0 reads Sentry, CloudWatch Logs, and deploy history from a GitOps-style infra repo. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Status

Early (v0). Tested against real incidents on one Kubernetes + AWS stack. Expect rough edges.

## Install

```sh
uv tool install git+https://github.com/AayushMiglani/truesight
```

## Use

```sh
cp truesight.example.toml truesight.toml   # set Sentry org, AWS profile, repo paths, model
export SENTRY_AUTH_TOKEN=...
export ANTHROPIC_API_KEY=...               # or the key for whichever LiteLLM model you set
aws sso login --profile prod

truesight investigate https://your-org.sentry.io/issues/API-1AZ/ --at 2026-10-23T11:30Z --no-llm   # Evidence only, nothing sent to a model
truesight investigate sentry:API-1AZ --at 2026-10-23T11:30Z                                       # full Report
truesight investigate sentry:API-1AZ --json > report.json
truesight investigate --from-ledger report.json                                                   # rerun synthesis on saved Evidence (works after Sentry/log retention expires)
```

What it expects of your stack (v0):

- Sentry events carry a request ID (tag or extra) that also appears in your service logs.
- Service logs in CloudWatch Logs, one log group per service.
- A GitOps infra repo where each service's prod config lives under one directory, and image tags are commit SHAs of your app repo.

All Evidence passes PII redaction before it is shown or sent to a model.

## Develop

```sh
uv sync
uv run pytest
```
