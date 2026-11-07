"""CloudWatch Logs Insights: follows a request ID across every service's log group."""

import time
from datetime import datetime, timedelta

from truesight.config import Config
from truesight.model import Evidence
from truesight.redact import redact_lines

POLL_SECONDS = 1
MAX_LINES = 200


def build_query(request_id: str) -> str:
    return (
        "fields @timestamp, @log, @message"
        f" | filter @message like /{request_id}/"
        f" | sort @timestamp asc | limit {MAX_LINES}"
    )


def service_of(log_field: str, template: str) -> str:
    """`@log` is `<account>:<group>`; invert the log group template to get the service."""
    group = log_field.split(":", 1)[-1]
    prefix, _, suffix = template.partition("{service}")
    return group.removeprefix(prefix).removesuffix(suffix)


def to_evidence(rows: list[dict], request_id: str, groups: list[str], template: str,
                start: datetime, end: datetime, region: str, partial: bool) -> tuple[Evidence, set[str]]:
    lines, services = [], set()
    for row in rows:
        svc = service_of(row["@log"], template)
        services.add(svc)
        lines.append(f"{row['@timestamp']} {svc:<20} {row['@message'].strip()[:400]}")
    if partial:
        lines.append("(query timed out: partial results)")
    snapshot, n = redact_lines(lines)
    return Evidence(
        source="cloudwatch-logs",
        kind="log lines",
        title=f"request {request_id[:8]}… across {len(services)} services",
        query=build_query(request_id) + f"  [groups: {', '.join(groups)}]",
        start=start,
        end=end,
        snapshot=snapshot,
        url=f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:logs-insights",
        redacted=n,
    ), services


def follow_request(cfg: Config, request_id: str, around: datetime) -> tuple[Evidence | None, set[str]]:
    import boto3  # deferred: tests and --help should not need AWS

    cw = cfg.cloudwatch
    template = cw.get("log_group", "{service}")
    groups = [template.format(service=s) for s in cfg.services][:50]  # Insights max 50 groups
    window = timedelta(minutes=cw.get("window_minutes", 15))
    start, end = around - window, around + window
    session = boto3.Session(profile_name=cw.get("profile"), region_name=cw.get("region"))
    logs = session.client("logs")
    qid = logs.start_query(
        logGroupNames=groups,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=build_query(request_id),
    )["queryId"]
    deadline = time.monotonic() + cw.get("timeout_seconds", 60)
    while True:
        resp = logs.get_query_results(queryId=qid)
        if resp["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        if time.monotonic() > deadline:
            logs.stop_query(queryId=qid)
            break
        time.sleep(POLL_SECONDS)
    if resp["status"] == "Failed":
        raise RuntimeError(f"Logs Insights query failed for {request_id}")
    rows = [{f["field"]: f["value"] for f in r} for r in resp["results"]]
    if not rows:
        return None, set()
    return to_evidence(rows, request_id, groups, template, start, end,
                       cw.get("region", ""), partial=resp["status"] != "Complete")
