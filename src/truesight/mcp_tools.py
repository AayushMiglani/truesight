"""Tools loaded from an MCP server. The agent loop stays synchronous."""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from truesight.tools import Tool


def tools_from_mcp(url: str) -> list[Tool]:
    """Wrap each tool on the server as a Tool the sync loop can call."""
    listed = asyncio.run(_list_tools(url))
    return [
        Tool(
            name=tool.name,
            description=tool.description or "",
            parameters=tool.inputSchema,
            function=_caller(url, tool.name),
        )
        for tool in listed
    ]


def _caller(url: str, name: str) -> Callable[..., str]:
    def function(**arguments: object) -> str:
        # Opening a session per call is a deliberate simplicity choice.
        return asyncio.run(_call_tool(url, name, arguments))

    return function


async def _list_tools(url: str):
    async with _session(url) as session:
        return (await session.list_tools()).tools


async def _call_tool(url: str, name: str, arguments: dict) -> str:
    async with _session(url) as session:
        result = await session.call_tool(name, arguments)
    text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
    if result.isError:
        return f"error: {text}"
    return text


@asynccontextmanager
async def _session(url: str):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
