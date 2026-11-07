"""Domain types. Names follow GLOSSARY.md."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Trigger:
    source: str  # "sentry"
    ref: str  # e.g. "LEDGER-5Y"
    url: str
    service: str
    title: str
    at: datetime  # time of the event the Investigation anchors on


@dataclass(frozen=True)
class Evidence:
    """A concrete artifact fetched from a team's tooling. Stores a snapshot plus the
    exact query and time range; the deep link is best effort."""

    source: str
    kind: str
    title: str
    query: str
    start: datetime
    end: datetime
    snapshot: tuple[str, ...]
    url: str | None = None
    redacted: int = 0
    id: str = ""  # assigned by the ledger (E1, E2, ...)


@dataclass(frozen=True)
class Gap:
    source: str
    what: str
    why: str


@dataclass(frozen=True)
class Finding:
    id: str
    claim: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class RuledOut:
    what: str
    why: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Hypothesis:
    id: str
    claim: str
    why_unbacked: str
    confirm: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    trigger: Trigger
    headline: str
    summary: str
    root_cause: str
    root_cause_findings: tuple[str, ...]
    findings: tuple[Finding, ...]
    hypotheses: tuple[Hypothesis, ...]
    ruled_out: tuple[RuledOut, ...]
    evidence: tuple[Evidence, ...]
    gaps: tuple[Gap, ...]
    next_steps: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)
