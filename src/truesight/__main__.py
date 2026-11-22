import argparse
import json
from dataclasses import asdict
from pathlib import Path

from truesight.agent import investigate
from truesight.mcp_tools import tools_from_mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m truesight",
        usage="python -m truesight [--mcp-url URL] [--context-file PATH] ALERT",
    )
    parser.add_argument("--mcp-url", metavar="URL")
    parser.add_argument("--context-file", metavar="PATH")
    parser.add_argument("alert", nargs="*")
    args = parser.parse_args(None if argv is None else argv[1:])
    if not args.alert:
        parser.print_usage()
        return
    alert = " ".join(args.alert)
    context = None
    if args.context_file is not None:
        context = Path(args.context_file).read_text(encoding="utf-8")
    tools = tools_from_mcp(args.mcp_url) if args.mcp_url else None
    answer = investigate(alert, tools=tools, context=context)
    print(json.dumps(asdict(answer), indent=2))


if __name__ == "__main__":
    main()
