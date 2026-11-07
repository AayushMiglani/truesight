"""Report renders: terminal text (verdict-first, variant A of the report-shape prototype) and JSON."""

import json
import textwrap
from dataclasses import asdict
from datetime import datetime

from truesight.model import Evidence, Gap, Report, Trigger

W = 100


def _wrap(text: str, indent: int, first: str | None = None) -> str:
    pad = " " * indent
    return textwrap.fill(text, W, initial_indent=pad if first is None else first, subsequent_indent=pad)


def _ev_line(e: Evidence) -> str:
    return f"     ↳ [{e.id}] {e.source:<16} {e.title[:48]:<48} {e.url or ''}"


def _header(t: Trigger) -> str:
    return f" {t.ref} · {t.service} · {t.at:%Y-%m-%d %H:%M} UTC · {t.url}"


def _gaps(gaps: tuple[Gap, ...]) -> list[str]:
    if not gaps:
        return []
    return ["", " NOT CHECKED", *(_wrap(f"{g.source}: {g.what} ({g.why})", 5, "   - ") for g in gaps)]


def text(r: Report) -> str:
    ev = {e.id: e for e in r.evidence}
    out = [_header(r.trigger), "", f" {r.headline}", "", " WHAT HAPPENED", _wrap(r.summary, 1)]
    refs = " ".join(f"[{i}]" for i in r.root_cause_findings)
    out += ["", f" LIKELY ROOT CAUSE {refs}", _wrap(r.root_cause, 1)]
    if r.findings:
        out += ["", " FINDINGS"]
        for f in r.findings:
            out.append(_wrap(f.claim, 5, f" {f.id:<4}"))
            out.extend(_ev_line(ev[i]) for i in f.evidence)
    if r.hypotheses:
        out += ["", " HYPOTHESES (not backed by Evidence)"]
        for h in r.hypotheses:
            out.append(_wrap(h.claim, 5, f" {h.id:<4}"))
            out.append(_wrap(h.why_unbacked, 5, "     why not a Finding: "))
            out.extend(f"     confirm: {c}" for c in h.confirm)
    if r.ruled_out:
        out += ["", " RULED OUT"]
        for x in r.ruled_out:
            out.append(_wrap(f"{x.what}: {x.why} " + " ".join(f"[{i}]" for i in x.evidence), 5, " ✗   "))
    if r.next_steps:
        out += ["", " NEXT", *(_wrap(n, 5, "   - ") for n in r.next_steps)]
    out += _gaps(r.gaps)
    return "\n".join(out)


def ledger(trigger: Trigger, evidence: tuple[Evidence, ...], gaps: tuple[Gap, ...]) -> str:
    """Evidence only, no model involved (--no-llm)."""
    out = [_header(trigger), ""]
    for e in evidence:
        out.append(f" [{e.id}] {e.title}  ({e.source} · {e.kind} · {e.start:%m-%d %H:%M}–{e.end:%H:%M} UTC)")
        out.append(_wrap(e.query, 10, "     query: "))
        out.extend(f"     │ {line[: W - 7]}" for line in e.snapshot)
        if e.redacted:
            out.append(f"     │ ({e.redacted} values redacted)")
        if e.url:
            out.append(f"     {e.url}")
    out += _gaps(gaps)
    return "\n".join(out)


def as_json(obj) -> str:
    return json.dumps(asdict(obj), indent=2, default=str, ensure_ascii=False)


def ledger_from_json(text: str) -> tuple[Trigger, tuple[Evidence, ...], tuple[Gap, ...]]:
    """Trigger, Evidence and Gaps back from a saved --json Report, to rerun synthesis
    after the sources have expired (Sentry retention, log retention)."""
    r = json.loads(text)
    when = datetime.fromisoformat
    trigger = Trigger(**{**r["trigger"], "at": when(r["trigger"]["at"])})
    evidence = tuple(
        Evidence(**{**e, "start": when(e["start"]), "end": when(e["end"]), "snapshot": tuple(e["snapshot"])})
        for e in r["evidence"]
    )
    return trigger, evidence, tuple(Gap(**g) for g in r["gaps"])
