import argparse
import json
from pathlib import Path

import pydantic_ai

from truesight.agent import investigate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m truesight",
        usage="python -m truesight [--mcp-url URL]... [--context-file PATH] [--trace PATH] ALERT",
    )
    parser.add_argument("--mcp-url", metavar="URL", action="append", default=[])
    parser.add_argument("--context-file", metavar="PATH", type=Path)
    parser.add_argument("--trace", metavar="PATH", type=Path)
    parser.add_argument("alert", nargs="*")
    args = parser.parse_args(None if argv is None else argv[1:])
    pydantic_ai.BANNER_ENABLED = False
    if not args.alert:
        parser.print_usage()
        return
    context = args.context_file.read_text(encoding="utf-8") if args.context_file else None
    answer = investigate(
        " ".join(args.alert), mcp_urls=args.mcp_url, context=context, trace=args.trace
    )
    print(json.dumps(answer.model_dump(), indent=2))


if __name__ == "__main__":
    main()
