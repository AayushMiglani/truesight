import json
import socket
import threading
import time

import pytest
from mcp.server.fastmcp import FastMCP

from truesight.agent import Answer, investigate
from truesight.llm import Reply, ToolCall
from truesight.mcp_tools import tools_from_mcp


class FakeLLM:
    """Scripted model. Records each complete() call and takes no network."""

    def __init__(self, replies: list[Reply]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append((list(messages), tools))
        return self._replies.pop(0)


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

    logs = tools["get_logs"]
    assert logs.description == "Fetch logs for a pod."
    assert logs.parameters["properties"]["pod"]["type"] == "string"
    assert logs.parameters["required"] == ["pod"]
    error = logs.function(pod="web")
    assert error.startswith("error:")
    assert "no logs for web" in error


def test_investigate_with_mcp_tools(mcp_url: str):
    llm = FakeLLM(
        [
            Reply(tool_calls=[ToolCall("call-1", "get_pods", {"namespace": "prod"})]),
            Reply(
                text=json.dumps(
                    {
                        "component": "web",
                        "fault_type": "crash",
                        "root_cause": "pod missing",
                        "explanation": "the pod list names web",
                    }
                )
            ),
        ]
    )
    answer = investigate("web down", llm=llm, tools=tools_from_mcp(mcp_url))
    assert answer == Answer(
        component="web",
        fault_type="crash",
        root_cause="pod missing",
        explanation="the pod list names web",
    )
    assert llm.calls[1][0][-1]["content"] == "pod web in prod"
