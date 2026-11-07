"""truesight investigate <sentry-url | sentry:ID> [--at ISO] [--no-llm] [--json]
   truesight investigate --from-ledger report.json [--json]"""

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from truesight import config, llm, render
from truesight.gather import gather
from truesight.synthesis import synthesise


def _parse_at(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="truesight")
    sub = p.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("investigate", help="investigate one Trigger")
    inv.add_argument("ref", nargs="?", help="Sentry issue URL, sentry:<ID>, or a bare issue ID")
    inv.add_argument("--from-ledger", metavar="REPORT_JSON",
                     help="skip gathering; rerun synthesis on the Evidence saved in a --json Report")
    inv.add_argument("--at", type=_parse_at, help="anchor on the event nearest this time (UTC ISO)")
    inv.add_argument("--config", default="truesight.toml")
    inv.add_argument("--no-llm", action="store_true", help="gather Evidence only; nothing goes to a model")
    inv.add_argument("--json", action="store_true")
    srv = sub.add_parser("mcp", help="serve the investigate tool to an MCP client over stdio")
    srv.add_argument("--config", default="truesight.toml")
    args = p.parse_args(argv)
    if args.cmd == "mcp":
        from truesight.mcp_server import serve  # deferred: MCP SDK only needed here
        serve(args.config)
        return 0
    if bool(args.ref) == bool(args.from_ledger):
        p.error("give exactly one of: a Trigger ref, or --from-ledger")

    cfg = config.load(args.config)
    t0 = time.monotonic()
    if args.from_ledger:
        try:
            trigger, evidence, gaps = render.ledger_from_json(Path(args.from_ledger).read_text())
        except (OSError, ValueError, KeyError, TypeError) as e:
            p.error(f"cannot read ledger {args.from_ledger}: {e}")
    else:
        trigger, evidence, gaps = gather(cfg, args.ref, args.at)
    if args.no_llm:
        print(render.ledger(trigger, evidence, gaps))
        return 0
    try:
        report = synthesise(llm.from_config(cfg), trigger, evidence, gaps)
    except ValueError as e:
        print(render.ledger(trigger, evidence, gaps))
        print(f"\nsynthesis failed: {e}", file=sys.stderr)
        return 1
    report = replace(report, meta={"duration_s": round(time.monotonic() - t0, 1), "model": cfg.llm.get("model")})
    print(render.as_json(report) if args.json else render.text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
