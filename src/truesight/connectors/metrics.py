"""Metric series around the Trigger, for the services on the request path.
Each `[[metrics]]` entry in truesight.toml is one series; it attaches to an Investigation
when one of its `services` is on the path. Logs say what failed; metrics say what was saturated."""

from datetime import datetime, timedelta, timezone

from truesight.config import Config
from truesight.model import Evidence

POINTS_BEFORE = 12  # enough history to show a baseline
POINTS_AFTER = 4
RISE = 1.5  # ponytail: fixed "it went up" threshold; per-metric when a flat-but-bad series gets missed


def period_for(age: timedelta) -> int:
    """CloudWatch keeps 1-min data 15 days, 5-min 63 days, 1-hour 455 days."""
    if age < timedelta(days=14):
        return 60
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
    return [m for m in cfg.metrics if services & set(m.get("services", []))]


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


def fetch(cfg: Config, spec: dict, at: datetime, now: datetime) -> Evidence:
    source = spec.get("source", "cloudwatch")
    if source == "cloudwatch":
        return cloudwatch_series(cfg, spec, at, now)
    raise ValueError(f"unknown metrics source {source!r}")
