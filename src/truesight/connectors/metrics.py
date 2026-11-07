"""Metric series around the Trigger, for the services on the request path.
Each `[[metrics]]` entry in truesight.toml is one series; it attaches to an Investigation
when one of its `services` is on the path. Logs say what failed; metrics say what was saturated."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from truesight.config import Config
from truesight.model import Evidence

POINTS_BEFORE = 12  # enough history to show a baseline
POINTS_AFTER = 4
MAX_SERIES = 3
RISE = 1.5  # ponytail: fixed "it went up" threshold; per-metric when a flat-but-bad series gets missed


def period_for(age: timedelta) -> int:
    """5 min (~30 points per window: the shape, without bloating the ledger), or 1 hour past
    CloudWatch's 63-day 5-min retention. Use a Maximum stat so short spikes survive."""
    if age < timedelta(days=62):
        return 300
    return 3600


def window(at: datetime, period: int) -> tuple[datetime, datetime]:
    before = max(timedelta(hours=2), timedelta(seconds=period * POINTS_BEFORE))
    after = max(timedelta(minutes=30), timedelta(seconds=period * POINTS_AFTER))
    return at - before, at + after


def summarise(points: list[tuple[datetime, float]], at: datetime) -> list[str]:
    """Baseline from the early window vs peak around the Trigger, when it first rose, then the series."""
    if not points:
        return ["no datapoints in the window"]
    before = [v for t, v in points if t < at] or [points[0][1]]
    early = before[: max(1, len(before) // 2)]  # the late pre-trigger points may already be the incident
    baseline = sum(early) / len(early)
    peak_t, peak = max(points, key=lambda p: p[1])
    rise = next((t for t, v in points if baseline > 0 and v >= RISE * baseline), None)
    lines = [f"early-window baseline {baseline:.4g} · peak {peak:.4g} at {peak_t:%m-%d %H:%M} UTC"
             f" · min {min(v for _, v in points):.4g}"
             + (f" · first ≥{RISE}x baseline at {rise:%m-%d %H:%M} UTC" if rise else f" · never ≥{RISE}x baseline")]
    series = [f"{t:%H:%M} {v:.4g}" for t, v in points]
    lines += [" | ".join(series[i:i + 6]) for i in range(0, len(series), 6)]
    return lines


def specs_for(cfg: Config, services: set[str]) -> list[dict]:
    """Specs whose services are on the path. `services = ["*"]` matches every path service.
    A spec with `{service}` in its query or title expands to one series per matching service."""
    out = []
    for spec in cfg.metrics:
        wanted = spec.get("services", [])
        matched = sorted(services if "*" in wanted else services & set(wanted))
        templated = any("{service}" in str(spec.get(k, "")) for k in ("query", "title"))
        if templated:
            out += [{k: v.replace("{service}", svc) if isinstance(v, str) else v for k, v in spec.items()}
                    for svc in matched]
        elif matched:
            out.append(spec)
    return out


def cloudwatch_series(cfg: Config, spec: dict, at: datetime, now: datetime) -> Evidence:
    import boto3  # deferred: tests and --help should not need AWS

    cw = cfg.cloudwatch
    period = period_for(now - at)
    start, end = window(at, period)
    stat = spec.get("stat", "Average")
    dims = [{"Name": k, "Value": v} for k, v in spec.get("dimensions", {}).items()]
    client = boto3.Session(profile_name=cw.get("profile"), region_name=cw.get("region")).client("cloudwatch")
    resp = client.get_metric_data(
        MetricDataQueries=[{"Id": "m", "MetricStat": {
            "Metric": {"Namespace": spec["namespace"], "MetricName": spec["metric"], "Dimensions": dims},
            "Period": period, "Stat": stat}}],
        StartTime=start, EndTime=end, ScanBy="TimestampAscending",
    )
    result = resp["MetricDataResults"][0]
    points = [(t.astimezone(timezone.utc), v) for t, v in zip(result["Timestamps"], result["Values"])]  # boto gives local tz
    if not points:
        raise LookupError("no datapoints in the window")
    dim_text = ",".join(f"{d['Name']}={d['Value']}" for d in dims)
    return Evidence(
        source="cloudwatch-metrics",
        kind="metric",
        title=spec.get("title") or f"{spec['metric']} {stat} ({dim_text})",
        query=f"{spec['namespace']} {spec['metric']} {stat} [{dim_text}] period {period}s",
        start=start,
        end=end,
        snapshot=tuple(summarise(points, at)),
    )


def prometheus_series(cfg: Config, spec: dict, at: datetime, now: datetime) -> Evidence:
    """PromQL range query against any Prometheus-compatible API (direct, or a Grafana datasource proxy)."""
    prom = cfg.raw.get("prometheus", {})
    if not prom.get("url"):
        raise ValueError("[prometheus] url is not set in truesight.toml")
    step = period_for(now - at)
    start, end = window(at, step)
    params = urllib.parse.urlencode({"query": spec["query"], "start": start.timestamp(),
                                     "end": end.timestamp(), "step": step})
    req = urllib.request.Request(prom["url"].rstrip("/") + "/api/v1/query_range?" + params)
    if prom.get("token_env"):
        req.add_header("Authorization", f"Bearer {cfg.secret(prom['token_env'])}")
    try:
        with urllib.request.urlopen(req, timeout=prom.get("timeout_seconds", 30)) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Prometheus {e.code}: {e.read()[:200]!r}") from e
    series = body.get("data", {}).get("result", [])
    if not series:
        raise LookupError("no datapoints in the window (beyond retention, or the query matched nothing)")
    lines = []
    for s in series[:MAX_SERIES]:
        labels = ",".join(f"{k}={v}" for k, v in s["metric"].items() if k != "__name__")
        points = [(datetime.fromtimestamp(t, timezone.utc), float(v)) for t, v in s["values"]]
        lines += ([f"series {{{labels}}}"] if labels or len(series) > 1 else []) + summarise(points, at)
    if len(series) > MAX_SERIES:
        lines.append(f"... {len(series) - MAX_SERIES} more series; aggregate the query (max/sum) to see them")
    return Evidence(
        source="prometheus",
        kind="metric",
        title=spec.get("title") or spec["query"],
        query=f"{spec['query']} step {step}s",
        start=start,
        end=end,
        snapshot=tuple(lines),
    )


def fetch(cfg: Config, spec: dict, at: datetime, now: datetime) -> Evidence:
    """Raises LookupError when the series is empty: the caller records a Gap, not Evidence."""
    source = spec.get("source", "cloudwatch")
    if source == "cloudwatch":
        return cloudwatch_series(cfg, spec, at, now)
    if source == "prometheus":
        return prometheus_series(cfg, spec, at, now)
    raise ValueError(f"unknown metrics source {source!r}")
