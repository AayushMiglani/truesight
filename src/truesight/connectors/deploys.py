"""Deploys from a GitOps-style infra repo: every commit that touched a service's
prod values file is a deploy or config change. Covers image bumps and flag flips."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from truesight.config import Config
from truesight.model import Evidence
from truesight.redact import redact_lines

SEP = "\x1f"
MAX_DIFF_LINES = 30
MAX_COMMITS = 40
MAX_FILES = 8
MAX_PATCHED_COMMITS = 3
MAX_PATCH_LINES = 60
MAX_RUNTIME_LINES = 40
# ponytail: keyword filter over values files; config key when a service needs other knobs.
RUNTIME_KEYS = r"-XX|-Xm[sx]|memory|cpu|replica|hikari|pool|timeout|max-|limits?:|requests:"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def diff_lines(patch: str) -> list[str]:
    return [
        line for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def image_tags(lines: list[str]) -> tuple[str | None, str | None]:
    """Old and new imageTag from a values diff, if the commit bumped the image."""
    def tag(sign: str) -> str | None:
        return next((l.split(":", 1)[1].strip(" '\"") for l in lines if l.startswith(sign) and "imageTag" in l), None)
    return tag("-"), tag("+")


def code_changes(cfg: Config, service: str, old: str, new: str) -> list[str]:
    """Commits shipped by an image bump (tags are commit SHAs in the code repo), newest first.
    Commits touching the service's own code paths are marked * and list their files."""
    d = cfg.deploys
    if not d.get("code_repo"):
        return []
    repo = Path(d["code_repo"]).expanduser()
    paths = [p.format(service=service) for p in d.get("code_paths", ["{service}/"])]
    try:
        all_commits = _git(repo, "log", "--format=%h %s", f"{old}..{new}").splitlines()
        own = _git(repo, "log", "--format=%x00%h", "--name-only", f"{old}..{new}", "--", *paths)
    except subprocess.CalledProcessError as e:
        return [f"code changes {old}..{new} unavailable: {e.stderr.strip()[:120]}"]
    files = {}
    for block in filter(None, own.split("\0")):
        sha, *names = block.strip().splitlines()
        files[sha] = [Path(n).name for n in names if n]
    out = [f"code {old}..{new}: {len(all_commits)} commits, * = touches {', '.join(paths)}"]
    for row in all_commits[:MAX_COMMITS]:
        sha = row.split(" ", 1)[0]
        mark = "*" if sha in files else " "
        out.append(f"{mark} {row}")
        if sha in files:
            out.append(f"    files: {', '.join(files[sha][:MAX_FILES])}")
    if len(all_commits) > MAX_COMMITS:
        out.append(f"... {len(all_commits) - MAX_COMMITS} more")
    for sha in list(files)[:MAX_PATCHED_COMMITS]:
        patch = _git(repo, "show", "--format=", "-U1", sha, "--", *paths)
        kept = [l for l in patch.splitlines() if l.startswith(("@@", "+++")) or diff_lines(l)]
        out.append(f"diff {sha} ({service} paths):")
        out.extend(kept[:MAX_PATCH_LINES])
        if len(kept) > MAX_PATCH_LINES:
            out.append(f"... {len(kept) - MAX_PATCH_LINES} more diff lines")
    return out


def runtime_config(cfg: Config, service: str, at: datetime) -> Evidence | None:
    """The service's prod runtime knobs (JVM flags, pools, timeouts, resources) as deployed at `at`.
    Catches causes that live in config nobody changed recently."""
    d = cfg.deploys
    repo = Path(d["repo"]).expanduser()
    path = d["path"].format(service=service)
    rev = _git(repo, "rev-list", "-1", f"--before={at.isoformat()}", "HEAD").strip()
    if not rev:
        return None
    grep = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-i", "-E", "-e", RUNTIME_KEYS, rev, "--", path],
                          capture_output=True, text=True)
    if grep.returncode > 1:  # 1 = no match, anything higher is a real failure
        raise RuntimeError(f"git grep failed: {grep.stderr.strip()[:120]}")
    found = grep.stdout
    lines = [l.split(":", 1)[1].replace(path, "", 1) for l in found.splitlines()]
    if not lines:
        return None
    snapshot, n = redact_lines(lines[:MAX_RUNTIME_LINES])
    return Evidence(
        source="git",
        kind="config",
        title=f"{service} prod runtime config as deployed",
        query=f"git grep -iE '{RUNTIME_KEYS}' {rev[:9]} -- {path}",
        start=at,
        end=at,
        snapshot=snapshot,
        url=d.get("commit_url", "").format(sha=rev) or None,
        redacted=n,
    )


def describe(service: str, lines: list[str]) -> str:
    """Summarise a values diff: image bump, config change, or both."""
    old, new = image_tags(lines)
    other = [l for l in lines if "imageTag" not in l]
    parts = []
    if new:
        parts.append(f"image {old or '?'} → {new}")
    if other:
        parts.append(f"{len(other)} config lines changed")
    return f"{service} prod: " + (", ".join(parts) or "values changed")


def changes(cfg: Config, service: str, since: datetime, until: datetime) -> list[Evidence]:
    d = cfg.deploys
    repo = Path(d["repo"]).expanduser()
    path = d["path"].format(service=service)
    log = _git(repo, "log", f"--since={since.isoformat()}", f"--until={until.isoformat()}",
               f"--format=%H{SEP}%cI{SEP}%s", "--reverse", "--", path)
    out = []
    for row in filter(None, log.splitlines()):
        sha, when, subject = row.split(SEP)
        lines = diff_lines(_git(repo, "show", "--format=", sha, "--", path))
        old, new = image_tags(lines)
        code = code_changes(cfg, service, old, new) if old and new else []
        snapshot, n = redact_lines([f"{sha[:9]} {when} {subject}", *lines[:MAX_DIFF_LINES], *code])
        at = datetime.fromisoformat(when).astimezone(timezone.utc)
        out.append(Evidence(
            source="git",
            kind="deploy",
            title=describe(service, lines),
            query=f"git log -- {path} ({since:%Y-%m-%d %H:%M} to {until:%Y-%m-%d %H:%M})",
            start=at,
            end=at,
            snapshot=snapshot,
            url=d.get("commit_url", "").format(sha=sha) or None,
            redacted=n,
        ))
    return out
