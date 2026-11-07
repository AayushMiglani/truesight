"""Deterministic first pass: Trigger, then follow the request, then deploys on its path.
Every fetch lands in the Evidence ledger; every failure lands in Gaps."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from truesight.config import Config
from truesight.connectors import cloudwatch, deploys, metrics, sentry
from truesight.model import Evidence, Gap, Trigger

MAX_IDS_FOLLOWED = 3


def _number(evidence: list[Evidence]) -> tuple[Evidence, ...]:
    return tuple(replace(e, id=f"E{i}") for i, e in enumerate(evidence, 1))


def gather(cfg: Config, ref: str, at: datetime | None) -> tuple[Trigger, tuple[Evidence, ...], tuple[Gap, ...]]:
    trigger, trigger_ev, ids = sentry.fetch_trigger(cfg, ref, at)
    evidence, gaps = [trigger_ev], []
    services = {trigger.service}

    if not ids:
        gaps.append(Gap("sentry", "correlation ID on the event", "none of the configured correlation_keys was set"))
    if cfg.cloudwatch:
        for name, value in list(ids.items())[:MAX_IDS_FOLLOWED]:
            try:
                ev, seen = cloudwatch.follow_request(cfg, value, trigger.at)
            except Exception as e:  # one backend failing must not end the Investigation
                gaps.append(Gap("cloudwatch-logs", f"{name} {value[:8]}…", str(e)))
                continue
            if ev is None:
                gaps.append(Gap("cloudwatch-logs", f"{name} {value[:8]}…", "no log line matched in the window"))
            else:
                evidence.append(ev)
                services |= seen

    if cfg.deploys:
        since = trigger.at - timedelta(hours=cfg.deploys.get("lookback_hours", 24))
        for svc in sorted(services):
            try:
                evidence.extend(deploys.changes(cfg, svc, since, trigger.at))
                runtime = deploys.runtime_config(cfg, svc, trigger.at)
                if runtime:
                    evidence.append(runtime)
            except Exception as e:
                gaps.append(Gap("git", f"deploys of {svc}", str(e)))

    now = datetime.now(timezone.utc)
    for spec in metrics.specs_for(cfg, services):
        try:
            evidence.append(metrics.fetch(cfg, spec, trigger.at, now))
        except Exception as e:
            gaps.append(Gap("metrics", spec.get("title") or spec.get("metric", "?"), str(e)))

    return trigger, _number(evidence), tuple(gaps)
