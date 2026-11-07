"""Sentry: resolves a Trigger reference into the Trigger, its Evidence, and the
correlation IDs to follow."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from truesight.config import Config
from truesight.model import Evidence, Trigger
from truesight.redact import redact_lines

_ISSUE_IN_URL = re.compile(r"/issues/([^/?#]+)")


def parse_ref(ref: str) -> str:
    """Accept a Sentry issue URL, `sentry:<id>`, or a bare short/numeric ID."""
    if ref.startswith("sentry:"):
        return ref.removeprefix("sentry:")
    if "://" in ref:
        m = _ISSUE_IN_URL.search(ref)
        if not m:
            raise ValueError(f"not a Sentry issue URL: {ref}")
        return m.group(1)
    return ref


def extract_ids(event: dict, keys: list[str]) -> dict[str, str]:
    """Pull correlation IDs out of an event. Keys look like `tag:request_id` or
    `extra:request_id`. Values are normalised: pipes stripped, upper-cased."""
    tags = {t["key"]: t["value"] for t in event.get("tags", [])}
    extra = event.get("context") or {}
    found = {}
    for key in keys:
        where, _, name = key.partition(":")
        value = tags.get(name) if where == "tag" else extra.get(name) if where == "extra" else None
        if value and name not in found:
            found[name] = str(value).strip("|").upper()
    return found


def _exception_line(event: dict) -> str | None:
    for entry in event.get("entries", []):
        if entry.get("type") == "exception":
            values = entry["data"].get("values") or []
            if values:
                last = values[-1]
                return f"{last.get('type')}: {last.get('value')}"
    return None


def _event_time(event: dict) -> datetime:
    return datetime.fromisoformat(event["dateCreated"].replace("Z", "+00:00"))


def build(issue: dict, event: dict, service: str, ids: dict[str, str]) -> tuple[Trigger, Evidence]:
    at = _event_time(event)
    lines = [issue.get("title", "")]
    if exc := _exception_line(event):
        lines.append(exc)
    lines.append(
        f"{issue.get('count')} events · {issue.get('userCount')} users · "
        f"first seen {issue.get('firstSeen')} · last seen {issue.get('lastSeen')}"
    )
    lines.append(f"event {event.get('eventID')} at {event['dateCreated']}")
    if trace := (event.get("contexts") or {}).get("trace", {}).get("trace_id"):
        lines.append(f"sentry trace_id {trace}")
    lines.extend(f"{k} {v}" for k, v in ids.items())
    snapshot, n = redact_lines(lines)
    trigger = Trigger(
        source="sentry",
        ref=issue.get("shortId", issue["id"]),
        url=issue.get("permalink", ""),
        service=service,
        title=issue.get("title", ""),
        at=at,
    )
    evidence = Evidence(
        source="sentry",
        kind="issue",
        title=trigger.ref,
        query=f"issue {trigger.ref}, event {event.get('eventID')}",
        start=at,
        end=at,
        snapshot=snapshot,
        url=trigger.url,
        redacted=n,
    )
    return trigger, evidence


class _Client:
    def __init__(self, cfg: Config):
        s = cfg.sentry
        self.base = s.get("host", "https://sentry.io").rstrip("/") + "/api/0/organizations/" + s["org"]
        self.token = cfg.secret(s.get("token_env", "SENTRY_AUTH_TOKEN"))

    def get(self, path: str, **params) -> dict | list:
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Sentry {e.code} for {path}") from e


def fetch_trigger(cfg: Config, ref: str, at: datetime | None) -> tuple[Trigger, Evidence, dict[str, str]]:
    client = _Client(cfg)
    issue_id = parse_ref(ref)
    if not issue_id.isdigit():
        issue_id = client.get(f"/shortids/{issue_id}/")["groupId"]
    issue = client.get(f"/issues/{issue_id}/")
    if at is None:
        event = client.get(f"/issues/{issue_id}/events/latest/")
    else:
        # The event nearest the given time, so a past incident anchors on its own window.
        window = dict(start=(at - timedelta(minutes=10)).isoformat(), end=(at + timedelta(minutes=10)).isoformat())
        events = client.get(f"/issues/{issue_id}/events/", full="true", **window)
        if not events:
            raise RuntimeError(f"no events for {ref} within 10 minutes of {at.isoformat()}")
        event = events[0]
    service = cfg.service_for_sentry_project(issue["project"]["slug"])
    ids = extract_ids(event, cfg.sentry.get("correlation_keys", []))
    trigger, evidence = build(issue, event, service, ids)
    return trigger, evidence, ids
