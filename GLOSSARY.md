# Truesight

Truesight investigates production errors and alerts on the user's own infrastructure: it follows the failing request across services, lines it up with deploys and metric changes, and reports what happened with evidence behind every claim.

## Language

### Investigation

**Trigger**:
The event that starts an Investigation: a Sentry issue or a fired alert.
_Avoid_: Incident, event, page

**Investigation**:
One run of Truesight's legwork, started from a single Trigger.
_Avoid_: Analysis, job, session

**Evidence**:
A concrete artifact from a team's tooling (a log line, a span, a metric series, a deploy event) carrying a deep link back to its source.
_Avoid_: Data, signal, source

**Finding**:
A claim about what happened that cites at least one piece of Evidence.
_Avoid_: Insight, conclusion

**Ruled-out Finding**:
A Finding that a suspected cause did not cause the failure, citing the Evidence that refutes it (for example, the same error on the image before a deploy).
_Avoid_: Red herring, dismissed hypothesis

**Hypothesis**:
A claim Truesight has not backed with Evidence, either because it was never tested or because testing was inconclusive; always shown apart from Findings, never passed off as one.
_Avoid_: Guess, speculation

**Report**:
The output of an Investigation: what happened, the likely root cause, and the Findings and Hypotheses behind it.
_Avoid_: Summary, RCA

**Postmortem draft**:
A first-draft postmortem document derived from a Report.
_Avoid_: Postmortem (the final, human-owned document is not Truesight's)

### Surfaces

**Surface**:
A place a human drives Truesight from: the CLI, Slack, or an MCP client such as Claude Code or Cursor.
_Avoid_: Frontend, client, interface
