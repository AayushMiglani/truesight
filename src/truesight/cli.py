"""truesight investigate <sentry-url | sentry:ID> [--at ISO] [--no-llm] [--json]"""

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

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
    inv.add_argument("ref", help="Sentry issue URL, sentry:<ID>, or a bare issue ID")
    inv.add_argument("--at", type=_parse_at, help="anchor on the event nearest this time (UTC ISO)")
    inv.add_argument("--config", default="truesight.toml")
    inv.add_argument("--no-llm", action="store_true", help="gather Evidence only; nothing goes to a model")
    inv.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    cfg = config.load(args.config)
    t0 = time.monotonic()
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
