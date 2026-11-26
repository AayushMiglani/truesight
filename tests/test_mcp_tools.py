import socket
import threading
import time

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from scripted import Scripted, call, submit

from truesight.agent import investigate
from truesight.answer import Answer

ARGS = {
    "status": "not_established",
    "summary": "web pod missing",
    "component": "web",
    "fault_type": "crash",
    "location": {"kind": "resource", "address": "pod web in prod"},
    "mechanism": "no pod serves web",
    "evidence": [{"tool": "get_pods prod", "finding": "pod web in prod"}],
    "ruled_out": [],
}


@pytest.fixture(scope="module")
def mcp_url() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = MCPServer("pods")

    @server.tool()
    def get_pods(namespace: str) -> str:
        """List pods in a namespace."""
        return f"pod web in {namespace}"

    @server.tool()
    def get_logs(pod: str) -> str:
        """Fetch logs for a pod."""
        raise ToolError(f"no logs for {pod}")

    thread = threading.Thread(
        target=lambda: server.run(transport="streamable-http", host="127.0.0.1", port=port),
        daemon=True,
    )
    thread.start()
    _wait_until_listening(port)
    return f"http://127.0.0.1:{port}/mcp"


def _wait_until_listening(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"MCP server did not listen on port {port}")


def test_investigate_with_mcp_tools(mcp_url: str):
    model = Scripted(
        [
            call("get_pods", {"namespace": "prod"}),
            call("get_logs", {"pod": "web"}, "call-2"),
            submit(ARGS),
        ]
    )
    assert investigate("web down", model=model, mcp_urls=[mcp_url]) == Answer.model_validate(ARGS)
    assert sorted(model.tool_names(0)) == ["get_logs", "get_pods", "submit_answer"]
    assert model.last_parts(1)[0].content == "pod web in prod"
    failed = model.last_parts(2)[0]
    assert failed.outcome == "failed"
    assert "no logs for web" in failed.model_response_str()
