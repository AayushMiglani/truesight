import socket
import threading
import time

import pytest
from mcp.server.fastmcp import FastMCP

from truesight.mcp_tools import tools_from_mcp


@pytest.fixture(scope="module")
def mcp_url() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = FastMCP("pods", host="127.0.0.1", port=port, log_level="ERROR")

    @server.tool()
    def get_pods(namespace: str) -> str:
        """List pods in a namespace."""
        return f"pod web in {namespace}"

    @server.tool()
    def get_logs(pod: str) -> str:
        """Fetch logs for a pod."""
        raise RuntimeError(f"no logs for {pod}")

    thread = threading.Thread(
        target=lambda: server.run(transport="streamable-http"),
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


def test_tools_from_mcp_lists_and_calls(mcp_url: str):
    tools = {tool.name: tool for tool in tools_from_mcp(mcp_url)}
    assert set(tools) == {"get_pods", "get_logs"}

    pods = tools["get_pods"]
    assert pods.description == "List pods in a namespace."
    assert pods.parameters["type"] == "object"
    assert pods.parameters["properties"]["namespace"]["type"] == "string"
    assert pods.parameters["required"] == ["namespace"]
    assert pods.function(namespace="prod") == "pod web in prod"

    error = tools["get_logs"].function(pod="web")
    assert error.startswith("error:")
    assert "no logs for web" in error
