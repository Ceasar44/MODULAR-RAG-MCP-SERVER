"""Real loopback HTTP server shared by protocol and agent contract tests."""

import asyncio
import socket
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import uvicorn
from mcp import types

from src.core.response.response_builder import MCPToolResponse
from src.mcp_server.fastmcp_adapter.app import create_fastmcp_server
from src.mcp_server.fastmcp_adapter.config import FastMCPServerSettings
from src.mcp_server.tools.get_document_summary import GetDocumentSummaryTool
from src.mcp_server.tools.list_collections import ListCollectionsTool
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool


@pytest.fixture
def tool_mocks(monkeypatch):
    mocks = {
        "query": AsyncMock(return_value=MCPToolResponse(
            content="Test knowledge [1]", citations=[], metadata={}, is_empty=False,
        )),
        "collections": AsyncMock(return_value=types.CallToolResult(content=[
            types.TextContent(type="text", text="test collection"),
        ])),
        "summary": AsyncMock(return_value=types.CallToolResult(content=[
            types.TextContent(type="text", text='{"title":"Test","summary":"Summary","metadata":{}}'),
        ])),
    }
    for cls, key in [(QueryKnowledgeHubTool, "query"), (ListCollectionsTool, "collections"),
                     (GetDocumentSummaryTool, "summary")]:
        monkeypatch.setattr(cls, "execute", mocks[key])
    return mocks


@pytest.fixture
def http_server(monkeypatch):
    monkeypatch.setattr("src.mcp_server.fastmcp_adapter.lifespan._preload_heavy_imports", lambda: None)

    @asynccontextmanager
    async def start(*, token=None, path="/mcp"):
        settings = FastMCPServerSettings(path=path, auth_enabled=token is not None, auth_token=token)
        mcp = create_fastmcp_server(settings)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            mcp.http_app(path=path), log_level="error", lifespan="on",
        ))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async def ready():
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("HTTP server exited during startup")
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(ready(), timeout=15)
            yield f"http://127.0.0.1:{port}{path}"
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(task, timeout=15)
            finally:
                sock.close()
    return start
