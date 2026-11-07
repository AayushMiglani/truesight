# Architecture (v0, walking skeleton)

Vocabulary: [GLOSSARY.md](GLOSSARY.md).

## Flow

```
truesight investigate <sentry-url | sentry:ID> [--at T]     (or MCP: truesight mcp → tool `investigate`)
  │
  ├─ gather.py          deterministic, no model involved
  │    1. connectors/sentry.py      Trigger + event → Evidence, correlation IDs (request_id)
  │    2. connectors/cloudwatch.py  Logs Insights `like /<id>/` across every service's log group
  │                                 → Evidence, plus the services on the request path
  │    3. connectors/deploys.py     git log of each path service's prod dir, 24 h back
  │                                 → one Evidence per image bump or config change; image bumps list
  │                                   the code commits shipped (+ diffs touching the service)
  │                                 → one Evidence of runtime knobs as deployed (JVM, pools, timeouts)
  │    4. connectors/metrics.py     each [[metrics]] series whose services are on the path, around
  │                                 the Trigger: early baseline, peak, when it first rose
  │    every snapshot passes redact.py; every failure becomes a Gap, never a crash
  │
  ├─ synthesis.py       one LLM call over the numbered ledger (E1..En) → JSON draft
  │    enforce(): a Finding whose citations are not in the ledger becomes a Hypothesis;
  │               a root cause with no surviving Finding is labelled unbacked;
  │               a ruled-out deploy with no citation becomes a Hypothesis
  │
  └─ render.py          terminal text (verdict first) or --json; --no-llm prints the ledger only
```

## Decisions taken to unblock building

Defaults, not final answers. Each is revisited when evaluation on a set of real past incidents (the golden set) shows it falling short.

| Area | Default | Revisit when |
|---|---|---|
| engine shape | Fixed gather, then one synthesis call. Citations enforced in code, not prompt. | Golden-set runs show the fixed pass misses Evidence a follow-up query would find (then: bounded agent loop over the same connectors). |
| request following | Follow `correlation_keys` IDs from the Sentry event through CloudWatch. No trace-ID pivot, no fuzzy fallback yet. | A Trigger has no request ID, or queue hops matter. |
| connector contract | Plain functions that return `Evidence`. No base class, no capability flags. | The second backend of the same kind (Datadog logs, Loki) arrives. |
| egress | LiteLLM, model is config. Redaction always on. `--no-llm` sends nothing. | The team picks the provider. |
| deploy correlation | Every prod values change in 24 h on the path is handed to the model as Evidence; the prompt forbids blaming a deploy on timing alone. | Golden-set incidents with a decoy deploy get blamed on it. |
| runtime | Python 3.12, `uv`, TOML config (stdlib), secrets by env var name. | Packaging for outside users. |
| service identity | `[services]` table keyed by k8s Deployment name; only overrides listed. | A service breaks the naming convention beyond `payments`. |

## Not built yet (in order)

1. Automated golden-set scoring, and a comparison with HolmesGPT.
2. Prometheus metrics Evidence (CloudWatch metrics are in).
3. Triggers beyond Sentry: Grafana alert, CloudWatch alarm.
4. Datadog connector.
