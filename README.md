<img src="assets/icon.svg" width="64" height="64" alt="">

# truesight

Investigates a production error on your own infrastructure: follows the failing request across services, lines it up with deploys, and reports what happened with Evidence behind every claim. A claim the Evidence does not back is shown as a Hypothesis, never as a Finding.

v0 reads Sentry, CloudWatch Logs, CloudWatch and Prometheus metrics, and deploy history from a GitOps-style infra repo. See [ARCHITECTURE.md](ARCHITECTURE.md).

[![ci](https://github.com/AayushMiglani/truesight/actions/workflows/ci.yml/badge.svg)](https://github.com/AayushMiglani/truesight/actions/workflows/ci.yml)

## Example

Anonymized and shortened from a real run. A deploy broke one call path; truesight followed the request through three services and named the PR.

```
 API-1AZ · gateway · 2026-10-23 11:30 UTC

 Gateway calls cards with an empty userId, producing a 404 on /cards/v1/users//link

 LIKELY ROOT CAUSE [F1] [F2] [F4]
 The gateway requests the per-user link with an empty userId, so cards has no route and returns
 404. The per-user call was introduced by PR #1234 (image a1b2c3d4), deployed to gateway at
 11:02 UTC, 25 minutes before the first event.

 FINDINGS
 F1  The failing request is GET /cards/v1/users//link: the userId segment is empty and cards
     answers 404.
     ↳ [E1] sentry           API-1AZ
     ↳ [E2] cloudwatch-logs  request 3F2A91C0… across 4 services
 F2  The same request carries a valid user id in the gateway and cards logs, so the id was
     available upstream but not put in the URL.
     ↳ [E2] cloudwatch-logs  request 3F2A91C0… across 4 services
 F4  Image a1b2c3d4 ships PR #1234 "Add the application id to the link", which changes
     CardService.java on the failing path.
     ↳ [E17] git              gateway prod: image 9f8e7d6c → a1b2c3d4

 HYPOTHESES (not backed by Evidence)
 H1  The caller that builds the link passes a null userId on one code path.
     why not a Finding: no log line shows the argument passed.
     confirm: log the userId argument at the call site and replay the request.

 RULED OUT
 ✗   gateway config change at 10:09 (logging level only) [E16]
 ✗   cards database saturation: CPU and connections flat around the error [E5] [E6]
```

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

## Use from an MCP client (Claude Code, Cursor, ...)

`truesight mcp` serves one tool, `investigate(ref, at?, evidence_only?)`, over stdio. It returns the same Report JSON as `--json`.

```sh
claude mcp add truesight \
  -e SENTRY_AUTH_TOKEN=... -e ANTHROPIC_API_KEY=... -e AWS_PROFILE=prod \
  -- truesight mcp --config /absolute/path/to/truesight.toml
```

Then ask: "investigate https://your-org.sentry.io/issues/API-1AZ/". An investigation takes 30 to 120 seconds.

What it expects of your stack (v0):

- Sentry events carry a request ID (tag or extra) that also appears in your service logs.
- Service logs in CloudWatch Logs, one log group per service.
- A GitOps infra repo where each service's prod config lives under one directory, and image tags are commit SHAs of your app repo.

All Evidence passes PII redaction before it is shown or sent to a model.

## Measure it on your own incidents

List past incidents with a known root cause in a TOML file (see [golden.example.toml](golden.example.toml)), then:

```sh
truesight eval golden.toml --runs 3                     # gather, synthesise 3 times each, judge each Report
truesight eval golden.toml --replay eval-runs/<dir>     # reuse saved Evidence after Sentry/log retention expires
```

A model call judges each Report: is the known cause the root cause, the top Hypothesis, a lower one, or missed, and was a decoy blamed. Several runs per incident, because the same Evidence can give different Reports.

## Develop

```sh
uv sync
uv run pytest
```
