import subprocess
from datetime import datetime, timedelta, timezone

from truesight.config import Config
from truesight.connectors import cloudwatch, deploys, sentry
from truesight.model import Evidence, Trigger
from truesight.redact import redact
from truesight.render import as_json, ledger_from_json
from truesight.synthesis import enforce, parse_json, synthesise

T = datetime(2026, 8, 19, 18, 13, tzinfo=timezone.utc)
RID = "9C1E2F7A0B3D4C5E8F6A7B8C9D0E1F2A"
TRIGGER = Trigger("sentry", "LEDGER-5Y", "https://x/issues/1/", "ledger", "Hikari", T)


def ev(i: str) -> Evidence:
    return Evidence("sentry", "issue", "t", "q", T, T, ("line",), id=i)


# --- redaction -----------------------------------------------------------------------------

def test_redacts_pii_but_keeps_request_and_trace_ids():
    line = f"|{RID}| user 9876543210 pan ABCDE1234F a@b.com from 10.0.0.1 trace 6ae9c97f0000000047ec2d37c37a5efa"
    out, n = redact(line)
    assert RID in out and "6ae9c97f0000000047ec2d37c37a5efa" in out
    assert "9876543210" not in out and "ABCDE1234F" not in out and "a@b.com" not in out and "10.0.0.1" not in out
    assert n == 4


# --- sentry --------------------------------------------------------------------------------

def test_parse_ref_forms():
    assert sentry.parse_ref("https://acme.sentry.io/issues/API-1AZ/") == "API-1AZ"
    assert sentry.parse_ref("https://acme.sentry.io/issues/1234567890/?project=1") == "1234567890"
    assert sentry.parse_ref("sentry:ORDERS-QN") == "ORDERS-QN"


def test_extract_ids_from_tag_or_extra():
    downstream = {"tags": [{"key": "request_id", "value": RID.lower()}]}
    gateway = {"tags": [], "context": {"request_id": f"|{RID}|"}}
    keys = ["tag:request_id", "extra:request_id"]
    assert sentry.extract_ids(downstream, keys) == {"request_id": RID}
    assert sentry.extract_ids(gateway, keys) == {"request_id": RID}
    assert sentry.extract_ids({"tags": []}, keys) == {}


def test_service_map_override():
    cfg = Config({"sentry": {}, "services": {"payments": {"sentry": "payments-service"}, "orders": {}}})
    assert cfg.service_for_sentry_project("payments-service") == "payments"
    assert cfg.service_for_sentry_project("orders") == "orders"
    assert cfg.service_for_sentry_project("unknown") == "unknown"


# --- cloudwatch ----------------------------------------------------------------------------

def test_service_of_log_group():
    tpl = "/aws/eks/logs/application/prod.{service}"
    assert cloudwatch.service_of("123456789012:/aws/eks/logs/application/prod.accounts", tpl) == "accounts"


def test_logs_to_evidence_lists_services_and_redacts():
    tpl = "prod.{service}"
    rows = [
        {"@timestamp": "18:12:40", "@log": "1:prod.accounts", "@message": f"|{RID}| call 9876543210"},
        {"@timestamp": "18:13:10", "@log": "1:prod.ledger", "@message": f"|{RID}| Hikari timeout"},
    ]
    e, seen = cloudwatch.to_evidence(rows, RID, ["g"], tpl, T, T, "us-east-1", partial=False)
    assert seen == {"accounts", "ledger"}
    assert e.redacted == 1 and "9876543210" not in "".join(e.snapshot)


# --- deploys (real git) --------------------------------------------------------------------

def _commit(repo, path, body, when):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(body)
    env = {"GIT_AUTHOR_DATE": when.isoformat(), "GIT_COMMITTER_DATE": when.isoformat(),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add svc for deployment"], check=True, env=env)


def test_deploy_changes_finds_image_bump_and_flag_flip(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = "services/app/ledger/prod/values.yaml"
    _commit(tmp_path, path, "imageTag: 1a2b3c4d\nflag: false\n", T - timedelta(days=3))
    ist = timezone(timedelta(hours=5, minutes=30))  # committer in IST, Report in UTC
    _commit(tmp_path, path, 'imageTag: "5e6f7a8b"\nflag: false\n', (T - timedelta(minutes=21)).astimezone(ist))
    _commit(tmp_path, path, 'imageTag: "5e6f7a8b"\nflag: true\n', T - timedelta(minutes=5))
    cfg = Config({"sentry": {}, "deploys": {"repo": str(tmp_path), "path": "services/app/{service}/prod/values.yaml"}})
    found = deploys.changes(cfg, "ledger", T - timedelta(hours=24), T)
    titles = [e.title for e in found]
    assert len(found) == 2  # the 3-day-old commit is outside the window
    assert titles[0] == "ledger prod: image 1a2b3c4d → 5e6f7a8b"  # oldest first
    assert f"{found[0].start:%H:%M}" == "17:52"  # converted to UTC
    assert "2 config lines changed" in titles[1]


def test_code_changes_lists_shipped_commits_and_marks_service_ones(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _commit(tmp_path, "gateway/A.java", "a", T)
    old = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    _commit(tmp_path, "orders/B.java", "b", T)
    _commit(tmp_path, "gateway/PaymentService.java", "c", T)
    new = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    cfg = Config({"sentry": {}, "deploys": {"code_repo": str(tmp_path)}})
    out = deploys.code_changes(cfg, "gateway", old, new)
    assert out[0].startswith(f"code {old}..{new}: 2 commits")
    assert out[1].startswith(f"* {new}") and out[2] == "    files: PaymentService.java"
    assert out[3].startswith("  ")  # orders commit shipped but not marked
    assert "unavailable" in deploys.code_changes(cfg, "gateway", "deadbeef", new)[0]
    assert deploys.code_changes(Config({"sentry": {}, "deploys": {}}), "gateway", old, new) == []


def test_runtime_config_reads_knobs_as_deployed_at_time(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = "services/app/orders/prod/values.yaml"
    _commit(tmp_path, path, "replicaCount: 2\nJAVA_TOOL_OPTIONS: -XX:MaxMetaspaceSize=256m\nname: orders\n", T - timedelta(days=30))
    _commit(tmp_path, path, "replicaCount: 2\nJAVA_TOOL_OPTIONS: -XX:MaxMetaspaceSize=512m\n", T + timedelta(hours=5))
    cfg = Config({"sentry": {}, "deploys": {"repo": str(tmp_path), "path": "services/app/{service}/prod/"}})
    e = deploys.runtime_config(cfg, "orders", T)
    assert e.snapshot == ("values.yaml:1:replicaCount: 2", "values.yaml:2:JAVA_TOOL_OPTIONS: -XX:MaxMetaspaceSize=256m")
    assert deploys.runtime_config(cfg, "orders", T - timedelta(days=60)) is None  # before any commit


# --- citation enforcement ------------------------------------------------------------------

def test_uncited_finding_is_demoted_and_root_cause_marked_unbacked():
    draft = {
        "headline": "h", "summary": "s",
        "root_cause": {"claim": "pool exhausted", "findings": ["F2"]},
        "findings": [
            {"id": "F1", "claim": "pool full", "evidence": ["E1"]},
            {"id": "F2", "claim": "made up", "evidence": ["E99"]},
        ],
        "hypotheses": [{"id": "H1", "claim": "stale stats", "why_unbacked": "no postgres", "confirm": ["ANALYZE"]}],
        "ruled_out": [
            {"what": "deploy 5e6f7a8b", "why": "predates", "evidence": ["E2"]},
            {"what": "deploy x", "why": "vibes", "evidence": []},
        ],
    }
    r = enforce(draft, TRIGGER, (ev("E1"), ev("E2")), ())
    assert [f.id for f in r.findings] == ["F1"]
    assert [h.claim for h in r.hypotheses] == ["made up", "stale stats", "Not the cause: deploy x"]
    assert [h.id for h in r.hypotheses] == ["H1", "H2", "H3"]
    assert [x.what for x in r.ruled_out] == ["deploy 5e6f7a8b"]
    assert r.root_cause.startswith("Unbacked") and r.root_cause_findings == ()


def test_synthesise_end_to_end_with_fake_model():
    def fake_llm(system, user):
        assert "[E1]" in user and "TRIGGER LEDGER-5Y" in user
        return '```json\n{"headline": "h", "summary": "s", "root_cause": {"claim": "c", "findings": ["F1"]},' \
               ' "findings": [{"id": "F1", "claim": "x", "evidence": ["E1"]}]}\n```'
    r = synthesise(fake_llm, TRIGGER, (ev("E1"),), ())
    assert r.root_cause == "c" and r.root_cause_findings == ("F1",)


def test_parse_json_rejects_prose():
    try:
        parse_json("no json here")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_saved_report_round_trips_to_the_same_ledger():
    ev = (Evidence("sentry", "issue", "LEDGER-5Y", "q", T, T, ("line",), "https://x", 1, "E1"),)
    report = enforce({"headline": "h", "summary": "s", "findings": []}, TRIGGER, ev, ())
    assert ledger_from_json(as_json(report)) == (TRIGGER, ev, ())


def test_mcp_investigate_turns_config_exit_into_tool_error(tmp_path):
    import pytest
    from truesight.mcp_server import investigate
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="config not found"):
        investigate(tmp_path / "missing.toml", "sentry:X-1")
