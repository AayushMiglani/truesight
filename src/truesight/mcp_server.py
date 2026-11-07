"""MCP surface: one `investigate` tool returning the same Report JSON as the CLI's --json.
Started by an MCP client over stdio: `truesight mcp --config /abs/path/truesight.toml`."""

import time
from dataclasses import asdict, replace
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from truesight import config, llm, render
from truesight.cli import _parse_at
from truesight.gather import gather
from truesight.synthesis import synthesise

INSTRUCTIONS = (
    "truesight investigates a production error from a Sentry issue: it follows the failing request "
    "through logs, lines it up with deploys and runtime config, and returns a Report where every "
    "Finding cites Evidence (E1, E2, ...). Claims without Evidence are Hypotheses, not Findings. "
    "Relay Findings with their Evidence ids; never present a Hypothesis as established."
)


def investigate(config_path: Path, ref: str, at: str | None = None, evidence_only: bool = False) -> str:
    try:
        cfg = config.load(config_path)
        t0 = time.monotonic()
        trigger, evidence, gaps = gather(cfg, ref, _parse_at(at) if at else None)
        if evidence_only:
            return render.as_json_value({"trigger": asdict(trigger), "evidence": [asdict(e) for e in evidence],
                                         "gaps": [asdict(g) for g in gaps]})
        report = synthesise(llm.from_config(cfg), trigger, evidence, gaps)
    except SystemExit as e:  # config/secret errors exit the CLI; here they must not kill the server
        raise ToolError(str(e.code)) from None
    except (RuntimeError, ValueError) as e:  # expected failures (Sentry API, bad model JSON): show the reason
        raise ToolError(str(e)) from e
    report = replace(report, meta={"duration_s": round(time.monotonic() - t0, 1), "model": cfg.llm.get("model")})
    return render.as_json(report)


def serve(config_path: str) -> None:
    path = Path(config_path).expanduser().resolve()
    server = MCPServer("truesight", instructions=INSTRUCTIONS)

    @server.tool(name="investigate", description=(
        "Investigate a production error. `ref`: Sentry issue URL, sentry:<SHORT-ID>, or issue id. "
        "`at`: optional UTC ISO time; anchors on the event nearest it (default: latest event). "
        "`evidence_only`: gather Evidence without calling a model. Takes 30-120 s. "
        "Returns Report JSON: headline, root_cause, findings (with evidence ids), hypotheses, "
        "ruled_out, evidence (snapshots + query + link), gaps."
    ))
    def investigate_tool(ref: str, at: str | None = None, evidence_only: bool = False) -> str:
        return investigate(path, ref, at, evidence_only)

    server.run("stdio")
