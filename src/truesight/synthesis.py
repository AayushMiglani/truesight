"""LLM synthesis over the Evidence ledger, with the citation rule enforced in code:
a Finding that cites no fetched Evidence is demoted to a Hypothesis."""

import json
import re
from collections.abc import Callable

from truesight.model import Evidence, Finding, Gap, Hypothesis, Report, RuledOut, Trigger

SYSTEM = """You investigate a production error. You are given a Trigger and an Evidence ledger
(E1, E2, ...) fetched from the team's tooling. Write a Report as JSON only, no prose around it:

{"headline": str, "summary": str,
 "root_cause": {"claim": str, "findings": [finding ids]},
 "findings": [{"id": "F1", "claim": str, "evidence": [evidence ids]}],
 "hypotheses": [{"id": "H1", "claim": str, "why_unbacked": str, "confirm": [str]}],
 "ruled_out": [{"what": str, "why": str, "evidence": [evidence ids]}],
 "next_steps": [str]}

Rules:
- A Finding states only what its cited Evidence shows. Cite at least one Evidence id.
- Anything you believe but the ledger does not show is a Hypothesis. Say how to confirm it.
- A deploy close in time to the error is not a cause by itself. Rule it out when the Evidence
  contradicts it (the error predates it, or its diff cannot touch the failing path); otherwise
  leave it as a Hypothesis.
- A deploy's time is when it was committed to the infra repo, not when it went live. Rollout and
  config reload lag by minutes to hours. Do not rule out a change, or its revert, because the
  commit is shortly before or after the error; weigh what the change does against the failure.
- A Sentry issue first seen long before the window is a recurring condition: ask what changed
  to make it fire now, including config that sets a limit the failure hits.
- If the ledger cannot explain the failure, say so in the root cause. Do not invent Evidence."""

Llm = Callable[[str, str], str]


def ledger_text(trigger: Trigger, evidence: tuple[Evidence, ...], gaps: tuple[Gap, ...]) -> str:
    parts = [f"TRIGGER {trigger.ref} ({trigger.service}) at {trigger.at.isoformat()}: {trigger.title}", ""]
    for e in evidence:
        parts.append(f"[{e.id}] {e.source} · {e.kind} · {e.title} · {e.start:%Y-%m-%d %H:%M}–{e.end:%H:%M} UTC")
        parts.extend(f"    {line}" for line in e.snapshot)
    if gaps:
        parts.append("\nNOT CHECKED")
        parts.extend(f"- {g.source}: {g.what} ({g.why})" for g in gaps)
    return "\n".join(parts)


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("model returned no JSON object")
    return json.loads(m.group(0))


def enforce(draft: dict, trigger: Trigger, evidence: tuple[Evidence, ...], gaps: tuple[Gap, ...]) -> Report:
    known = {e.id for e in evidence}
    findings, hypotheses, ruled_out = [], [], []

    for f in draft.get("findings", []):
        cited = tuple(i for i in f.get("evidence", []) if i in known)
        if cited:
            findings.append(Finding(f["id"], f["claim"], cited))
        else:
            hypotheses.append((f["claim"], "cited no fetched Evidence", ()))

    for h in draft.get("hypotheses", []):
        hypotheses.append((h["claim"], h.get("why_unbacked", ""), tuple(h.get("confirm", []))))

    for r in draft.get("ruled_out", []):
        cited = tuple(i for i in r.get("evidence", []) if i in known)
        if cited:
            ruled_out.append(RuledOut(r["what"], r.get("why", ""), cited))
        else:
            hypotheses.append((f"Not the cause: {r['what']}", "ruled out without citing fetched Evidence", ()))

    surviving = {f.id for f in findings}
    rc = draft.get("root_cause", {})
    rc_findings = tuple(i for i in rc.get("findings", []) if i in surviving)
    rc_claim = rc.get("claim", "")
    if rc_claim and not rc_findings:
        rc_claim = f"Unbacked (hypothesis): {rc_claim}"

    return Report(
        trigger=trigger,
        headline=draft.get("headline", trigger.title),
        summary=draft.get("summary", ""),
        root_cause=rc_claim,
        root_cause_findings=rc_findings,
        findings=tuple(findings),
        hypotheses=tuple(Hypothesis(f"H{i}", *h) for i, h in enumerate(hypotheses, 1)),
        ruled_out=tuple(ruled_out),
        evidence=evidence,
        gaps=gaps,
        next_steps=tuple(draft.get("next_steps", [])),
    )


def synthesise(llm: Llm, trigger: Trigger, evidence: tuple[Evidence, ...], gaps: tuple[Gap, ...]) -> Report:
    draft = parse_json(llm(SYSTEM, ledger_text(trigger, evidence, gaps)))
    return enforce(draft, trigger, evidence, gaps)
