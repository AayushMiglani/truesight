import argparse
import json
import sys
from enum import IntEnum
from pathlib import Path
from urllib.parse import urlparse

from pydantic_ai import AgentRunError

from truesight.agent import MaxStepsExceeded, investigate
from truesight.settings import ConfigError
from truesight.telemetry import configure_sentry

MAX_ALERT_CHARS = 4_000
MAX_CONTEXT_CHARS = 100_000
USAGE = "python -m truesight [--mcp-url URL]... [--context-file PATH] [--trace PATH] ALERT"


class Exit(IntEnum):
    ESTABLISHED = 0
    FAILED = 1
    USAGE = 2
    NOT_ESTABLISHED = 3


class InputError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(None if argv is None else argv[1:])
    alert = " ".join(args.alert).strip()
    if not alert:
        parser.print_usage()
        return Exit.ESTABLISHED
    try:
        _check_alert(alert)
        context = _read_context(args.context_file)
        configure_sentry()
        answer = investigate(alert, mcp_urls=args.mcp_url, context=context, trace=args.trace)
    except (InputError, ConfigError) as exc:
        return _fail(Exit.USAGE, str(exc))
    except (AgentRunError, MaxStepsExceeded) as exc:
        return _fail(Exit.FAILED, f"investigation failed: {exc}")
    print(json.dumps(answer.model_dump(), indent=2))
    return Exit.ESTABLISHED if answer.status == "established" else Exit.NOT_ESTABLISHED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m truesight", usage=USAGE)
    parser.add_argument("--mcp-url", metavar="URL", action="append", default=[], type=_mcp_url)
    parser.add_argument("--context-file", metavar="PATH", type=Path)
    parser.add_argument("--trace", metavar="PATH", type=Path)
    parser.add_argument("alert", nargs="*")
    return parser


def _mcp_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise argparse.ArgumentTypeError(f"not an http(s) URL: {value!r}")
    return value


def _check_alert(alert: str) -> None:
    if len(alert) > MAX_ALERT_CHARS:
        raise InputError(f"alert is {len(alert)} characters; the limit is {MAX_ALERT_CHARS}")


def _read_context(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read --context-file {path}: {exc}") from exc
    if len(text) > MAX_CONTEXT_CHARS:
        raise InputError(
            f"--context-file {path} is {len(text)} characters; the limit is {MAX_CONTEXT_CHARS}"
        )
    return text


def _fail(code: Exit, message: str) -> int:
    print(f"truesight: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
